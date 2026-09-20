"""Кто режет вывод подпроцесса СВОЕЙ РУКОЙ — и читает ли при этом перечень.

Заказ **G50, п. 2** приказа владельца «Portfolio CIO» (хвост ADR-427).

## Вопрос, на который прибор отвечает

ADR-427 измерил ОДНУ проводку прогонов — общую (``copy_independence_probe._run``,
хвост ``(stdout)[-keep:]``) — и назвал остаток дословно: *«`_run` здесь не
единственная проводка подпроцессов в дереве: ``subprocess.run(...,
capture_output=True)`` зовётся из многих мест своими руками. Сколько из них
ОБРЕЗАЮТ вывод своей рукой (срез, ``head``, ``[-N:]``) и сколько при этом
читают перечень — не мерено»*.

Перепись задаёт ту же пару вопросов ВТОРОЙ проводке:

1. **режет ли зовущий вывод своей рукой** — срез по знакам или по строкам,
   либо ``head``/``tail`` прямо в командной строке;
2. **читает ли он обрезанное как ПЕРЕЧЕНЬ** — то есть живёт ли ответ в
   элементах, которых срез мог не оставить.

## Что здесь НОВОГО против ADR-427, и почему это не копия

У общей проводки сторона разреза ОДНА и задана её кодом: режется голова,
остаётся хвост. Поэтому там «читатель сводки» был безопасен ПО ПОСТРОЕНИЮ —
сводка pytest живёт в хвосте. Своей рукой режут в обе стороны, и сторона
разреза становится **измеряемым полем каждого вызова**, а не свойством
проводки:

* ``[-N:]`` — ``head_cut``: уносит ГОЛОВУ, оставляет хвост (сводка цела);
* ``[:N]`` — ``tail_cut``: уносит ХВОСТ, оставляет голову (**сводка pytest
  теряется**, и ровно то чтение, что у общей проводки безопасно, здесь
  смертельно);
* ``[a:b]`` — ``window_cut``: уносит обе стороны.

Предполагать сторону, как у общей проводки, здесь значило бы завести вторую
копию правила, у которой посылка неверна (класс ADR-417/418).

## Односторонность — та же, и она сильная

Срез может только УБРАТЬ элементы, добавить — никогда. Значит всякий вывод,
сделанный из обрезанного перечня, смещён в одну сторону: «такого имени среди
них нет», «таких деревьев не осталось». Это НЕ ИЗМЕРЕНО, поданное под видом
ответа (инв. #17), и ошибается оно в сторону молчания. Сторона разреза меняет,
ЧТО именно пропало, но не меняет направления вреда.

## Прозу от вердикта прибор отделяет, и это объявлено

Обрезанное значение, ушедшее в СООБЩЕНИЕ (``"\\n".join(...)``, f-строка,
``log.warning``, ``raise``), вердикта не производит: человек увидит меньше
строк, но код не ответит ложно. Такие вызовы кладутся в ``prose_cut`` и
находкой НЕ объявляются — тем же правилом, каким ADR-427 не считает читателем
``print``. Прибор меряет, **может ли молча соврать ВЫВОД**, а не «всё ли видит
человек»; второй вопрос законен, но он другой, и смешивать их значило бы
покрасить полдерева.

## Происхождение значения, а не совпадение имени

Срез засчитывается, только если срезаемое ПРОИСХОДИТ от захваченного вывода:
якорь — имя, связанное вызовом, дальше до неподвижной точки идут производные
(``.stdout``, ``.splitlines()``, ``json.loads(...)``, срез, ``or``/``+``).
**Контейнер производной НЕ является** — ``doc = {"out": proc.stdout}`` не
делает ``doc`` выводом; это дословно правило из `.claude/rules/deployment.md`
(авария 2026-08-04), и ослабить его здесь значило бы оправдать ту же бомбу.
Поэтому ``args[:2]`` в сообщении об ошибке находкой не станет: ``args`` —
команда, а не её вывод.

## Дверь — не своя, а ввезённая

Различать «перечень кончился» и «перечень обрезали» умеет
``truncated_input_census`` (``door_named`` — метка ``output_truncated``;
``door_count`` — сверка с объявленным числом). Правило двери берётся **ввозом**
из него, а не переписывается здесь: две копии одного правила разошлись бы
молча (ADR-418, ``single_copy_by_import``). По той же причине ввозится и
правило «обход строк с накоплением».

Цена ввоза названа: правило двери у соседа ШИРОКОЕ — любая сверка ``len(...)``
в теле зовущего читается как ``door_count``, в том числе сверка длины КОМАНДЫ.
Ложная дверь возможна, и ошибается она в сторону молчания. Сужать правило надо
У ИСТОЧНИКА (обеим переписям сразу), а не заводить здесь свою копию: развилка
дороже промаха, который сегодня не реализовался ни разу (``guarded`` = 0).

## Три исхода различимы (инв. #17)

``sites == classified + unreadable`` закреплено тестом. Форма связывания,
которую разбор не проследил; потребитель среза, которого правило не узнало;
граница среза, не сводимая к числу, — всё это ``unmeasured`` С ПРИЧИНОЙ.
Корень дерева или каталог населения не прочитан ⇒ статус ``UNMEASURED`` и
ненулевой код возврата: «не измерено» никогда не выдаётся за «чисто».

## Чего перепись НЕ доказывает

* **Что обрезание вредит СЕГОДНЯ.** Вред требует, чтобы вывод однажды перерос
  границу среза; длина вывода — свойство машины и минуты, а не дерева.
* **Что необрезанный зовущий читает свой перечень ВЕРНО.** Отсутствие среза —
  не верность разбора.
* **Что население полно.** Population — прямые вызовы ``subprocess.run`` /
  ``subprocess.check_output`` с захваченным выводом. ``Popen`` считается
  отдельным числом (``popen_sites``) и в разбор не входит: его вывод читается
  через ``communicate()``, и это другая форма. Срез, сделанный за пределами
  функции-зовущего (значение вернули наружу), правилу не виден — такой вызов
  уходит в ``escaped``.
* **Что прозой обрезанное безвредно для ЧЕЛОВЕКА.** Оно безвредно для
  ВЕРДИКТА; сколько владелец не увидел в дайджесте — вопрос другого прибора.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
# Правило двери и правило «обход строк» — ВВОЗОМ, не копией (ADR-418).
from spa_core.monitoring.truncated_input_census import (  # noqa: E402
    DOOR_COUNT,
    DOOR_NAMED,
    has_door,
    iterates_lines,
)
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "hand_truncation_census.json"
#: Какой МОДУЛЬ собрал документ (константа; «кто позвал» — `invoked_by`).
PRODUCER = "spa_core/monitoring/hand_truncation_census.py"

#: Вторая общая проводка: модуль stdlib и функции, чей вывод можно захватить.
RUNNER_MODULE = "subprocess"
RUNNER_FUNCS = ("run", "check_output")
#: Форма, объявленная вне разбора (её вывод читается через `communicate()`).
OUT_OF_SCOPE_FUNCS = ("Popen",)

#: Каталоги населения. Тесты исключены той же причиной, что у соседа: тест не
#: производит артефакта, и его короткий перечень виден его же вердиктом.
SCAN_DIRS = ("spa_core", "scripts")

#: Срез по знакам либо по элементам — единица разреза.
UNIT_CHARS = "chars"
UNIT_ITEMS = "items"
UNIT_UNRESOLVED = "unresolved"

#: Сторона разреза. У общей проводки она одна и задана кодом; здесь — поле.
SIDE_HEAD = "head_cut"      # [-N:] — уносит голову
SIDE_TAIL = "tail_cut"      # [:N]  — уносит хвост
SIDE_WINDOW = "window_cut"  # [a:b] — уносит обе стороны
SIDE_COMMAND = "command_cut"  # head/tail прямо в команде
SIDE_UNRESOLVED = "unresolved"

READ_LIST = "list_read"
READ_PROSE = "prose_read"
READ_UNMEASURED = "unmeasured"

CLASS_SILENT = "silent_hand_cut"
CLASS_GUARDED = "guarded"
CLASS_PROSE = "prose_cut"
CLASS_ESCAPED = "escaped"
CLASS_NO_CUT = "no_hand_cut"
CLASS_UNMEASURED = "unmeasured"
FINDING_CLASSES = (CLASS_SILENT,)

#: Имена, чей вызов делает из значения ПРОЗУ: вердикта они не производят.
_PROSE_SINKS = frozenset({
    "join", "print", "format", "str", "repr", "warning", "error", "info",
    "debug", "exception", "critical", "log", "write", "fail", "_fail",
})

#: Имена, чей вызов превращает текст в КОЛЛЕКЦИЮ.
_SPLITTERS = frozenset({"splitlines", "split", "rsplit", "readlines"})
_LOADERS = frozenset({"loads", "load"})


class NotMeasured(RuntimeError):
    """Корень населения или каталог не прочитан — третий исход."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------- разбор ввоза

def runner_aliases(tree: ast.AST, module: str = RUNNER_MODULE) -> Set[str]:
    """Под какими именами модуль проводки виден в ЭТОМ файле.

    Разбирается AST, а не текст: ``import subprocess as sp`` полного имени в
    вызове не оставляет, а слово ``subprocess`` в комментарии вызовом не
    является (урок ADR-417).
    """
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is None:
            continue
    return names


def _call_target(node: ast.Call) -> Tuple[Optional[str], Optional[str]]:
    """``(квалификатор, имя)`` вызова: ``subprocess.run`` → ``('subprocess', 'run')``."""
    func = node.func
    if isinstance(func, ast.Name):
        return None, func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id, func.attr
    if isinstance(func, ast.Attribute):
        return None, func.attr
    return None, None


def is_captured(node: ast.Call, fname: str) -> bool:
    """Захвачен ли вывод этим вызовом.

    ``check_output`` захватывает ПО ПОСТРОЕНИЮ; у ``run`` захват объявляют
    ``capture_output=True`` либо переданный ``stdout``.
    """
    if fname == "check_output":
        return True
    for kw in node.keywords:
        if kw.arg == "capture_output":
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
        if kw.arg == "stdout":
            return True
    return False


def command_cut(node: ast.Call) -> bool:
    """Режет ли САМА команда: ``head``/``tail`` элементом argv либо в строке."""
    if not node.args:
        return False
    argv = node.args[0]
    if isinstance(argv, (ast.List, ast.Tuple)):
        for elt in argv.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str) \
                    and elt.value in ("head", "tail"):
                return True
        return False
    if isinstance(argv, ast.Constant) and isinstance(argv.value, str):
        return " head " in f" {argv.value} " or " tail " in f" {argv.value} "
    return False


# ------------------------------------------------- происхождение от захвата

def _derives_from(expr: ast.AST, known: Set[str]) -> bool:
    """Происходит ли ЗНАЧЕНИЕ выражения от захваченного вывода.

    Контейнер производной НЕ является: ``{"out": proc.stdout}`` не делает
    значение выводом (`.claude/rules/deployment.md`, авария 2026-08-04). Иначе
    «RHS содержит якорь» оправдало бы ровно ту бомбу, против которой правило.
    """
    if isinstance(expr, ast.Name):
        return expr.id in known
    if isinstance(expr, ast.Attribute):
        return _derives_from(expr.value, known)
    if isinstance(expr, ast.Subscript):
        return _derives_from(expr.value, known)
    if isinstance(expr, ast.Await):
        return _derives_from(expr.value, known)
    if isinstance(expr, ast.BoolOp):
        return any(_derives_from(v, known) for v in expr.values)
    if isinstance(expr, ast.BinOp):
        return _derives_from(expr.left, known) or _derives_from(expr.right, known)
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Attribute) and _derives_from(func.value, known):
            return True
        _, fname = _call_target(expr)
        if fname in _LOADERS or fname in _SPLITTERS:
            return any(_derives_from(a, known) for a in expr.args)
        return False
    if isinstance(expr, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        return any(_derives_from(gen.iter, known) for gen in expr.generators)
    return False


def derived_names(func: ast.AST, anchor: str) -> Set[str]:
    """Имена, чьё значение происходит от якоря — до неподвижной точки."""
    known = {anchor}
    for _ in range(12):  # предел обхода; ниже проверяется сходимость
        grew = False
        for node in ast.walk(func):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _derives_from(value, known):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in _target_names(target):
                    if name not in known:
                        known.add(name)
                        grew = True
        if not grew:
            break
    return known


def _target_names(target: ast.AST) -> List[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: List[str] = []
        for elt in target.elts:
            out.extend(_target_names(elt))
        return out
    return []


def anchor_of(stmt: ast.Assign) -> Optional[str]:
    """Имя, которому связан РЕЗУЛЬТАТ прогона.

    ``proc = subprocess.run(...)`` — само имя; ``out = subprocess.run(...).stdout``
    разбирается тем же способом, потому что срез и атрибут — производные.
    """
    if len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if isinstance(target, ast.Name):
        return target.id
    return None


# ------------------------------------------------------------ единица и сторона

def _produces_collection(expr: ast.AST) -> bool:
    """Даёт ли выражение КОЛЛЕКЦИЮ (а не текст)."""
    if isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.List,
                         ast.Tuple)):
        return True
    if isinstance(expr, ast.Call):
        _, fname = _call_target(expr)
        return fname in _SPLITTERS or fname in _LOADERS or fname in ("list", "sorted")
    return False


def cut_unit(expr: ast.AST, collections_: Set[str]) -> str:
    """Что режет срез: знаки текста или элементы перечня."""
    if _produces_collection(expr):
        return UNIT_ITEMS
    if isinstance(expr, ast.Name):
        return UNIT_ITEMS if expr.id in collections_ else UNIT_CHARS
    if isinstance(expr, ast.Attribute):
        return UNIT_CHARS
    if isinstance(expr, (ast.BoolOp, ast.BinOp, ast.Subscript, ast.Call)):
        return UNIT_CHARS
    return UNIT_UNRESOLVED


def collection_names(func: ast.AST, known: Set[str]) -> Set[str]:
    """Производные имена, связанные КОЛЛЕКЦИЕЙ."""
    out: Set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in known \
                and _produces_collection(node.value):
            out.add(node.targets[0].id)
    return out


def cut_side(node: ast.Slice) -> str:
    """Сторона разреза — ПОЛЕ вызова, а не свойство проводки."""
    lower, upper = node.lower, node.upper
    lower_zero = lower is None or (isinstance(lower, ast.Constant)
                                   and lower.value == 0)
    if lower is not None and not lower_zero and upper is None:
        # `[-N:]` и `[N:]` — обе формы уносят ГОЛОВУ, разной длины.
        return SIDE_HEAD
    if lower_zero and upper is not None:
        return SIDE_TAIL
    if lower is not None and upper is not None:
        return SIDE_WINDOW
    return SIDE_UNRESOLVED


def _is_budget_bound(expr: Optional[ast.AST], consts: Dict[str, int]) -> bool:
    """Граница-БЮДЖЕТ: литерал либо имя модульной целой константы."""
    if expr is None:
        return False
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int) \
            and not isinstance(expr.value, bool):
        return True
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.USub):
        return _is_budget_bound(expr.operand, consts)
    if isinstance(expr, ast.Name):
        return expr.id in consts
    return False


def is_cut(node: ast.Slice, consts: Dict[str, int]) -> bool:
    """Срез ли это БЮДЖЕТОМ — или разбор потока по вычисленным границам.

    Разделяет форма ГРАНИЦЫ, а не намерение автора: ``buf[nl + 1:nl + 1 + size]``
    режет ровно столько, сколько объявил сам вывод, — материала такой срез не
    теряет и бюджетом не является. ``subjects[:80]`` теряет, и это видно по
    границе. Намерения прибор не читает — и говорит об этом вслух.
    """
    if node.lower is None and node.upper is None:
        return False
    return (_is_budget_bound(node.lower, consts)
            or _is_budget_bound(node.upper, consts))


def module_int_consts(tree: ast.AST) -> Dict[str, int]:
    """Целые константы уровня модуля — материал для границ вида ``[:KEEP]``."""
    out: Dict[str, int] = {}
    body = tree.body if isinstance(tree, ast.Module) else []
    for node in body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, int) \
                and not isinstance(node.value.value, bool):
            out[node.targets[0].id] = node.value.value
    return out


# -------------------------------------------------------------- род потребления

class _Parents:
    """Родители узлов одной функции: чем СТАЛО обрезанное значение."""

    def __init__(self, func: ast.AST):
        self.of: Dict[int, ast.AST] = {}
        for node in ast.walk(func):
            for child in ast.iter_child_nodes(node):
                self.of[id(child)] = node

    def parent(self, node: ast.AST) -> Optional[ast.AST]:
        return self.of.get(id(node))


def consumption_of(cut: ast.AST, func: ast.AST, parents: _Parents,
                   unit: str) -> Tuple[str, str]:
    """Чем стало обрезанное значение: ``(род, причина-если-не-измерено)``."""
    node: ast.AST = cut
    parent = parents.parent(node)
    while isinstance(parent, (ast.Subscript, ast.Attribute)):
        node, parent = parent, parents.parent(parent)
    # Кортеж или список ПРЯМО в `return` — это возврат нескольких значений,
    # а не хранилище: читатель у него ровно тот же, что у самого возврата.
    while isinstance(parent, (ast.Tuple, ast.List)) \
            and isinstance(parents.parent(parent), ast.Return):
        node, parent = parent, parents.parent(parent)
    # Именованный аргумент — это вызов, а не контейнер.
    if isinstance(parent, ast.keyword):
        node, parent = parent, parents.parent(parent)
    if parent is None:
        return READ_UNMEASURED, "у среза нет родительского узла в теле функции"
    if isinstance(parent, ast.comprehension) or (
            isinstance(parent, ast.For) and parent.iter is node):
        # Обход РАДИ СООБЩЕНИЯ перечнем не является: `"\n".join(f(x) for x in
        # cut)` производит прозу, и ответа о членстве из него никто не берёт.
        if isinstance(parent, ast.comprehension):
            outer = parents.parent(parent)
            sink = parents.parent(outer) if outer is not None else None
            if isinstance(sink, ast.Call) and _call_target(sink)[1] in _PROSE_SINKS:
                return READ_PROSE, ""
        return READ_LIST, ""
    if isinstance(parent, ast.Compare):
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops):
            return READ_LIST, ""
        return READ_PROSE, ""
    if isinstance(parent, ast.Return):
        return (READ_LIST if unit == UNIT_ITEMS else READ_PROSE), ""
    if isinstance(parent, (ast.JoinedStr, ast.FormattedValue, ast.BinOp)):
        return READ_PROSE, ""
    if isinstance(parent, ast.Call):
        _, fname = _call_target(parent)
        if fname in _PROSE_SINKS:
            return READ_PROSE, ""
        if fname in ("len", "sorted", "list", "set", "enumerate", "any", "all"):
            return READ_LIST, ""
        return READ_UNMEASURED, (
            f"обрезанное ушло в `{fname or '?'}` — правило не знает, читает ли "
            f"тот перечень")
    if isinstance(parent, (ast.Assign, ast.AnnAssign)):
        targets = (parent.targets if isinstance(parent, ast.Assign)
                   else [parent.target])
        names = [n for t in targets for n in _target_names(t)]
        if not names:
            form = type(targets[0]).__name__ if targets else "?"
            return READ_UNMEASURED, (
                f"обрезанное связано формой `{form}`: перенос между операторами "
                f"через хранилище правилу не виден")
        return _consumption_of_name(names[0], func, unit)
    if isinstance(parent, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        return READ_UNMEASURED, (
            "обрезанное положено в контейнер: дальнейший читатель правилу не виден")
    return READ_PROSE, ""


def _consumption_of_name(name: str, func: ast.AST, unit: str) -> Tuple[str, str]:
    """Как читается ИМЯ, связанное обрезанным значением."""
    seen_any = False
    for node in ast.walk(func):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) \
                and node.iter.id == name:
            return READ_LIST, ""
        if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            for gen in node.generators:
                if isinstance(gen.iter, ast.Name) and gen.iter.id == name:
                    return READ_LIST, ""
        if isinstance(node, ast.Compare):
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops) \
                    and any(isinstance(side, ast.Name) and side.id == name
                            for side in [node.left, *node.comparators]):
                return READ_LIST, ""
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name) \
                and node.value.id == name:
            return (READ_LIST if unit == UNIT_ITEMS else READ_PROSE), ""
        # Только ЧТЕНИЕ имени. Цель присваивания — тоже `ast.Name`, и считать
        # её читателем значило бы сделать ветку «читателя нет» недостижимой:
        # связанное значение всегда «прочтено» самим фактом связывания.
        if isinstance(node, ast.Name) and node.id == name \
                and isinstance(node.ctx, ast.Load):
            seen_any = True
    if not seen_any:
        return READ_UNMEASURED, (
            f"имя `{name}` связано обрезанным значением, но читателя в теле нет")
    # Имя читается, но ни обходом, ни членством, ни возвратом — это проза.
    return READ_PROSE, ""


# ------------------------------------------------------------------- вердикт

def classify_site(cut_found: bool, consumption: str, door: Optional[str],
                  escaped: bool) -> str:
    """Вердикт одного вызова.

    Порядок ветвей существен: «не измерено» спрашивается ПЕРВЫМ, иначе
    неразобранная форма молча получила бы самый спокойный ярлык.
    """
    if consumption == READ_UNMEASURED:
        return CLASS_UNMEASURED
    if not cut_found:
        return CLASS_ESCAPED if escaped else CLASS_NO_CUT
    if consumption != READ_LIST:
        return CLASS_PROSE
    return CLASS_GUARDED if door else CLASS_SILENT


def _population(root: Path) -> List[Path]:
    root = Path(root)
    if not root.is_dir():
        raise NotMeasured(f"корень дерева не прочитан: {root}")
    out: List[Path] = []
    for sub in SCAN_DIRS:
        base = root / sub
        if not base.is_dir():
            raise NotMeasured(f"каталог населения не прочитан: {base}")
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
                continue
            out.append(path)
    if not out:
        raise NotMeasured(f"в дереве {root} не нашлось ни одного файла населения")
    return out


def _enclosing_functions(tree: ast.Module) -> List[Tuple[str, ast.AST]]:
    out: List[Tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node))
    return out


def _escapes(func: ast.AST, known: Set[str]) -> bool:
    """Ушло ли производное значение НАРУЖУ — возвратом из функции."""
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None \
                and _derives_from(node.value, known):
            return True
    return False


def capture_wrappers(tree: ast.Module, aliases: Set[str]) -> Set[str]:
    """Функции модуля, чей ВОЗВРАТ происходит от захваченного вывода.

    Глубина ОДНА, и это объявлено: обёртка обёртки правилу не видна (то же
    правило, что у соседа ADR-427). Зовущий такой обёртки получает вывод
    подпроцесса, и срез у него — та же рука.
    """
    out: Set[str] = set()
    for name, func in _enclosing_functions(tree):
        anchors: Set[str] = set()
        for stmt in ast.walk(func):
            if not isinstance(stmt, ast.Assign):
                continue
            call = stmt.value
            if not isinstance(call, ast.Call):
                continue
            qual, fname = _call_target(call)
            if qual in aliases and fname in RUNNER_FUNCS \
                    and is_captured(call, fname):
                anchor = anchor_of(stmt)
                if anchor:
                    anchors.add(anchor)
        if not anchors:
            continue
        known = derived_names(func, next(iter(sorted(anchors))))
        for a in anchors:
            known |= derived_names(func, a)
        if _escapes(func, known):
            out.add(name)
    return out


def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    """Перепись: каждый ВЫЗОВ второй проводки ложится ровно в одну корзину."""
    root = Path(root)
    files = _population(root)

    rows: List[dict] = []
    unreadable: List[dict] = []
    popen_sites: List[str] = []
    parse_slices: List[str] = []
    uncaptured = 0

    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            unreadable.append({"module": rel,
                               "reason": f"{type(exc).__name__}: {exc}"})
            continue
        aliases = runner_aliases(tree)
        if not aliases:
            continue
        consts = module_int_consts(tree)
        wrappers = capture_wrappers(tree, aliases)

        for enclosing, func in _enclosing_functions(tree):
            parents = _Parents(func)
            for stmt in ast.walk(func):
                if not isinstance(stmt, ast.Assign):
                    continue
                call = stmt.value
                if not isinstance(call, ast.Call):
                    continue
                qual, fname = _call_target(call)
                via = ""
                if qual is None and fname in wrappers and fname != enclosing:
                    # Зовущий обёртки держит в руках тот же вывод подпроцесса.
                    via = fname
                elif qual not in aliases:
                    continue
                elif fname in OUT_OF_SCOPE_FUNCS:
                    popen_sites.append(f"{rel}:{call.lineno}")
                    continue
                elif fname not in RUNNER_FUNCS:
                    continue
                elif not is_captured(call, fname):
                    uncaptured += 1
                    continue

                anchor = anchor_of(stmt)
                if anchor is None:
                    form = (type(stmt.targets[0]).__name__
                            if stmt.targets else "?")
                    rows.append({
                        "module": rel, "enclosing": enclosing,
                        "line": call.lineno, "call": (f"{qual}.{fname}" if qual else fname),
                        "via_wrapper": via,
                        "cut_side": "", "cut_unit": "", "cut_line": None,
                        "consumption": READ_UNMEASURED, "door": "",
                        "verdict": CLASS_UNMEASURED,
                        "reason": (
                            f"результат связан формой `{form}` (не имя): "
                            f"перенос между операторами через хранилище "
                            f"правилу не виден")})
                    continue

                known = derived_names(func, anchor)
                collections_ = collection_names(func, known)
                cuts: List[Tuple[ast.Subscript, str, str]] = []
                for node in ast.walk(func):
                    if not isinstance(node, ast.Subscript) \
                            or not isinstance(node.slice, ast.Slice):
                        continue
                    if not _derives_from(node.value, known):
                        continue
                    if not is_cut(node.slice, consts):
                        parse_slices.append(f"{rel}:{node.lineno}")
                        continue
                    cuts.append((node, cut_side(node.slice),
                                 cut_unit(node.value, collections_)))

                by_command = command_cut(call)
                if not cuts and by_command:
                    # Режет сама команда: значения в дереве не срезаны, но
                    # перечень всё равно неполон.
                    consumption = (READ_LIST if iterates_lines(func)
                                   else READ_PROSE)
                    door = has_door(func)
                    rows.append({
                        "module": rel, "enclosing": enclosing,
                        "line": call.lineno, "call": (f"{qual}.{fname}" if qual else fname),
                        "via_wrapper": via,
                        "cut_side": SIDE_COMMAND, "cut_unit": UNIT_ITEMS,
                        "cut_line": call.lineno, "consumption": consumption,
                        "door": door or "",
                        "verdict": classify_site(True, consumption, door, False),
                        "reason": ""})
                    continue

                if not cuts:
                    escaped = _escapes(func, known)
                    rows.append({
                        "module": rel, "enclosing": enclosing,
                        "line": call.lineno, "call": (f"{qual}.{fname}" if qual else fname),
                        "via_wrapper": via,
                        "cut_side": "", "cut_unit": "", "cut_line": None,
                        "consumption": (READ_LIST if iterates_lines(func)
                                        else READ_PROSE),
                        "door": "", "escaped": escaped,
                        "verdict": classify_site(False, READ_PROSE, None, escaped),
                        "reason": ""})
                    continue

                # Вызов с несколькими срезами судится по САМОМУ опасному: один
                # обрезанный перечень не лечится соседним безопасным срезом.
                worst = None
                for node, side, unit in cuts:
                    consumption, reason = consumption_of(node, func, parents, unit)
                    door = has_door(func) if consumption == READ_LIST else None
                    verdict = classify_site(True, consumption, door, False)
                    rank = {CLASS_SILENT: 0, CLASS_UNMEASURED: 1,
                            CLASS_GUARDED: 2, CLASS_PROSE: 3}.get(verdict, 4)
                    row = {
                        "module": rel, "enclosing": enclosing,
                        "line": call.lineno, "call": (f"{qual}.{fname}" if qual else fname),
                        "via_wrapper": via,
                        "cut_side": SIDE_COMMAND if by_command else side,
                        "cut_unit": unit, "cut_line": node.lineno,
                        "consumption": consumption, "door": door or "",
                        "verdict": verdict, "reason": reason}
                    if worst is None or rank < worst[0]:
                        worst = (rank, row)
                if worst is not None:
                    rows.append(worst[1])

    order = {CLASS_SILENT: 0, CLASS_UNMEASURED: 1, CLASS_GUARDED: 2,
             CLASS_PROSE: 3, CLASS_ESCAPED: 4, CLASS_NO_CUT: 5}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), r["module"], r["line"]))
    counts = {cls: sum(1 for r in rows if r["verdict"] == cls)
              for cls in (CLASS_SILENT, CLASS_GUARDED, CLASS_PROSE,
                          CLASS_ESCAPED, CLASS_NO_CUT, CLASS_UNMEASURED)}
    counts["unreadable"] = len(unreadable)
    sides = {}
    for row in rows:
        if row.get("cut_side"):
            sides[row["cut_side"]] = sides.get(row["cut_side"], 0) + 1
    findings = [r for r in rows if r["verdict"] in FINDING_CLASSES]
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "FINDING" if findings else "CLEAN",
        "question": ("кто режет вывод подпроцесса СВОЕЙ РУКОЙ и читает ли при "
                     "этом перечень"),
        "population_rule": (
            f"spa_core/ + scripts/, без тестов; в население входит ВЫЗОВ "
            f"{RUNNER_MODULE}.{{{','.join(RUNNER_FUNCS)}}} с ЗАХВАЧЕННЫМ выводом "
            f"(capture_output=True либо переданный stdout; check_output — по "
            f"построению). Ввоз разбирается AST, не текстом. Срез засчитывается "
            f"только если срезаемое ПРОИСХОДИТ от захваченного вывода; "
            f"контейнер производной не является"),
        "runner": {"module": RUNNER_MODULE, "funcs": list(RUNNER_FUNCS),
                   "doors": [DOOR_NAMED, DOOR_COUNT],
                   "doors_imported_from":
                       "spa_core/monitoring/truncated_input_census.py"},
        "scanned": len(files),
        "call_sites": len(rows),
        "counts": counts,
        "cut_sides": sides,
        "rows": rows,
        "unreadable": unreadable,
        # Поверхности, объявленные ВНЕ разбора, — числом, а не обещанием.
        "popen_sites": sorted(popen_sites),
        # Срезы по ВЫЧИСЛЕННЫМ границам: разбор потока, а не бюджет.
        "parse_slices": sorted(set(parse_slices)),
        "uncaptured_sites": uncaptured,
        "what_it_does_not_prove": [
            "что обрезание вредит СЕГОДНЯ: вред требует, чтобы вывод перерос "
            "границу среза; длина вывода — свойство машины, а не дерева",
            "что no_hand_cut читает свой перечень ВЕРНО — отсутствие среза не "
            "есть верность разбора",
            "что население полно: Popen объявлен вне разбора и посчитан "
            "отдельно, срез за пределами функции-зовущего виден как escaped",
            "что prose_cut безвреден для ЧЕЛОВЕКА: он безвреден для ВЕРДИКТА",
            "что дверь засчитана ВЕРНО: правило двери ввозится у соседа и оно "
            "ШИРОКОЕ — любая сверка len(...) в теле зовущего читается как "
            "door_count. Ввоз выбран сознательно (две копии разошлись бы "
            "молча), но цена названа: ложная дверь возможна и ошибается она в "
            "сторону молчания. Сужать правило надо У ИСТОЧНИКА, а не здесь",
        ],
    }


def report(doc: dict, *, max_rows: int = 20) -> List[str]:
    """Строки отчёта. Единственное место, где перепись становится текстом."""
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — "
                f"{observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    sides = observed(doc, "cut_sides", kind=dict) or {}
    classified = sum(counts.get(c, 0) for c in
                     (CLASS_SILENT, CLASS_GUARDED, CLASS_PROSE, CLASS_ESCAPED,
                      CLASS_NO_CUT, CLASS_UNMEASURED))
    out = [
        f"кто режет вывод СВОЕЙ РУКОЙ (заказ G50 п. 2): {status} · вызовов "
        f"{doc.get('call_sites')} · РЕЖЕТ ПЕРЕЧЕНЬ МОЛЧА "
        f"{counts.get(CLASS_SILENT)} · с дверью {counts.get(CLASS_GUARDED)} · "
        f"срез в прозу {counts.get(CLASS_PROSE)} · без среза "
        f"{counts.get(CLASS_NO_CUT)} · ушло наружу {counts.get(CLASS_ESCAPED)} · "
        f"не измерено {counts.get(CLASS_UNMEASURED)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[СТОРОНА РАЗРЕЗА] "
        + (" · ".join(f"{k} {v}" for k, v in sorted(sides.items())) or "срезов нет")
        + " — у своей руки сторона ПОЛЕ вызова, а не свойство проводки: "
          "[:N] уносит хвост со сводкой, [-N:] уносит голову с перечнем",
        f"[УЧЁТ] осмотрено файлов {doc.get('scanned')} · вызовов "
        f"{doc.get('call_sites')} = разобрано {classified} + не разобрано "
        f"{counts.get('unreadable')} · вне разбора: Popen "
        f"{len(doc.get('popen_sites') or [])}, без захвата "
        f"{doc.get('uncaptured_sites')}, разбор потока срезом "
        f"{len(doc.get('parse_slices') or [])}",
    ]
    findings = [r for r in (doc.get("rows") or [])
                if r["verdict"] in FINDING_CLASSES]
    for row in findings[:max_rows]:
        out.append(
            f"[НАХОДКА] {row['module']}:{row['line']} `{row['enclosing']}`: срез "
            f"{row['cut_side']} по {row['cut_unit']} (строка {row['cut_line']}) "
            f"читается как ПЕРЕЧЕНЬ и двери нет")
    if len(findings) > max_rows:
        # Умолчание об укорочении и есть способ соврать усечением (ADR-427).
        out.append(f"[…] показаны {max_rows} находки из {len(findings)}; "
                   f"полный перечень — в артефакте")
    unmeasured = [r for r in (doc.get("rows") or [])
                  if r["verdict"] == CLASS_UNMEASURED]
    for row in unmeasured[:5]:
        out.append(f"[НЕ ИЗМЕРЕНО] {row['module']}:{row['line']} "
                   f"`{row['enclosing']}` — {row.get('reason') or 'причина не записана'}")
    out.append("НЕ ДОКЛАДЫВАЕТ: вредит ли обрезание сегодня (длина вывода — "
               "свойство машины); сколько строк не увидел ЧЕЛОВЕК у prose_cut")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Отрисовка для шага 0-офис. Второй копии правила отрисовки здесь НЕТ."""
    lines = report(doc, max_rows=max_rows)
    if str(doc.get("status")) == "FINDING":
        lines[0] = f"⚠️ {lines[0]}"
    return lines


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        data_dir: Optional[Path] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> dict:
    """Один прогон переписи для ступени моста.

    Гейта такта здесь нет: зов есть разбор AST в одном процессе и стои́т
    секунды (та же причина, что у соседа ADR-427). Недельный такт не купил бы
    ничего, а завёл бы вторую копию правила срока.
    """
    root = Path(root)
    target = (Path(dest) if dest is not None
              else (Path(data_dir) if data_dir is not None
                    else root / "data") / ARTIFACT)
    try:
        doc = measure(root, now=now)
    except NotMeasured as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись обрезания вывода своей рукой (заказ G50 п. 2)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    outcome = run(Path(args.root),
                  dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    doc = outcome["doc"]
    for line in report(doc):
        print(line)
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
