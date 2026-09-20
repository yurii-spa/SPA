"""Обрезан ли ВХОД у зовущего общей проводки прогонов — перепись.

Заказ **G49, п. 2** приказа владельца «Portfolio CIO» (хвост ADR-426).

## Вопрос, на который прибор отвечает

Общая проводка прогонов (``copy_independence_probe._run``) возвращает не весь
вывод подпроцесса, а его ХВОСТ: ``(stdout)[-keep:]``. Умолчание бюджета —
``KEEP_OUTPUT_CHARS``. Замер #643 нашёл у ОДНОГО её зовущего вред: сбор тестов
печатал 81 строку, бюджет оставлял 20, и «теста нет» выдавалось за ответ.
Починен был тот зовущий. Заказ назвал остаток дословно: *«Бюджет вывода — это
свойство общей проводки, и зонд был не единственным её зовущим. Кто из зовущих
читает ПЕРЕЧЕНЬ (а не сводку) — перечислить и назвать число; „сводку читают
все“ есть догадка, пока её никто не мерил»*.

## Почему хвост спасает одних и убивает других

Обрезание режет ГОЛОВУ. Значит вред зависит не от длины вывода, а от того, ГДЕ
живёт ответ читателя:

* **сводка pytest, последняя строка ``git rev-parse``, код возврата** живут в
  хвосте — обрезание их не трогает НИКОГДА, и это свойство по построению, а не
  сегодняшняя удача;
* **перечень** (имена упавших тестов, строки ``git worktree list --porcelain``,
  адреса сбора) живёт по всему выводу — обрезание уносит его голову МОЛЧА, и
  короткий перечень неотличим от короткого ответа.

Поэтому перепись делит зовущих не по длине и не по команде, а по РОДУ ЧТЕНИЯ.

## Вред односторонний, и это существенно

Обрезание может только УБРАТЬ элементы перечня, добавить — никогда. Значит
всякий вывод, сделанный из укороченного перечня, смещён в одну сторону:
«такого имени среди упавших нет», «таких деревьев не осталось», «такого теста
не собрано». Каждое из них есть НЕ ИЗМЕРЕНО, поданное под видом ответа
(инв. #17), и каждое ошибается в опасную сторону — в сторону молчания.

Живой замер 20.09, ради которого заказ и написан: ``git worktree list
--porcelain`` в этом репозитории — **6506 знаков, 51 дерево**; через бюджет
2000 до читателя доходит **11 из 51**, то есть 40 строк не доходит ни при
каком состоянии мира. Уборщик осиротевших деревьев зондов читает ИМЕННО этот
перечень.

## Две формы двери, и обе названы

Читатель перечня защищён, если у него есть дверь, различающая «перечень
кончился» и «перечень обрезали»:

* ``door_named`` — вызов ``output_truncated(...)``: проводка САМА метит место
  разреза, читатель метку спрашивает;
* ``door_count`` — сверка ``len(перечень)`` с числом, объявленным в самом
  выводе (так устроен ``_collected_ids`` после ADR-426: pytest объявляет
  «N tests collected», и разобранный перечень обязан с этим числом сойтись).
  Сверяемое обязано ПРОИСХОДИТЬ от вывода (заказ G51 п. 3): прежнее правило
  засчитывало любую сверку ``len(...)`` в теле, включая длину КОМАНДЫ, и
  ошибалось в сторону молчания — ложная дверь превращает находку в
  ``guarded``. Отклонённые сверки не исчезают: каждая названа в строке
  (``door_declined``), а их число стоит в сводке.

Вторая форма СТАРШЕ первой и на своём участке сильнее — поэтому она
засчитывается, а не переписывается под общий шаблон. Дверь, которая не может
сработать, есть украшение (`.claude/rules/deployment.md`), и дописывать
``output_truncated`` туда, где арифметика уже закрыла класс, прибор не требует.

## Три исхода различимы (инв. #17) и учёт тождественен

``scanned == classified + unreadable`` закреплено тестом. Бюджет, не сводимый
к числу; читатель, чьё тело не найдено; форма связывания, которую разбор не
узнал, — всё это ``unmeasured`` С ПРИЧИНОЙ, а не «сводка». Корень дерева или
сам модуль проводки не прочитан ⇒ статус ``UNMEASURED`` и ненулевой код
возврата: «не измерено» никогда не выдаётся за «чисто».

## Чего перепись НЕ доказывает

* **Что обрезание произошло СЕГОДНЯ.** Длина вывода есть свойство машины и
  минуты, а не дерева; прибор читает, может ли потеря случиться МОЛЧА.
  Единственное место, где вред измерен числом, — ``git worktree list`` выше, и
  измерен он рукой, а не этим прибором.
* **Что ``tail_safe`` читает свой хвост ВЕРНО.** Род чтения — не верность
  разбора.
* **Что население полно.** Глубина обёрток — ОДНА (функция модуля, чьё тело
  возвращает вызов проводки). Обёртка обёртки правилу не видна, и её
  поверхность считается отдельно (``wrapper_depth_exceeded``).
* **Что у ``silent_truncation`` есть вред.** Вред требует, чтобы вывод однажды
  перерос бюджет. Перепись называет, что о перерастании не узнает никто.
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
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "truncated_input_census.json"
#: Какой МОДУЛЬ собрал документ (константа; «кто позвал» — `invoked_by`).
PRODUCER = "spa_core/monitoring/truncated_input_census.py"

#: Общая проводка прогонов и её бюджет. Путь и ИМЕНА — здесь; ЧИСЛО бюджета
#: прибор читает из самого модуля разбором, а не хранит: вторая копия числа
#: разошлась бы молча (ADR-417).
RUNNER_MODULE = "spa_core/monitoring/copy_independence_probe.py"
RUNNER_FUNC = "_run"
RUNNER_BUDGET_NAME = "KEEP_OUTPUT_CHARS"
#: Имя двери «проводка пометила разрез».
TRUNCATION_DOOR = "output_truncated"

#: Каталоги населения. Тесты исключены: тест не производит артефакта, и его
#: короткий перечень виден его же вердиктом.
SCAN_DIRS = ("spa_core", "scripts")

CLASS_SILENT = "silent_truncation"
CLASS_GUARDED = "guarded"
CLASS_TAIL_SAFE = "tail_safe"
CLASS_UNBOUNDED = "unbounded"
CLASS_UNMEASURED = "unmeasured"
FINDING_CLASSES = (CLASS_SILENT,)

READ_LIST = "list_read"
READ_TAIL = "tail_read"
READ_NONE = "code_only"


class NotMeasured(RuntimeError):
    """Корень населения или модуль проводки не прочитан — третий исход."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------- разбор ввоза

def alias_map(tree: ast.AST, runner_module: str = RUNNER_MODULE) -> Set[str]:
    """Под какими именами модуль проводки виден в ЭТОМ файле.

    Разбирается AST, а не текст: ``from pkg import mod`` полного имени в тексте
    не оставляет, и текстовое правило выдумало бы находку у файла, который
    проводку лишь упоминает в комментарии (урок ADR-417).
    """
    dotted = runner_module[:-3].replace("/", ".")
    pkg, _, leaf = dotted.rpartition(".")
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == pkg:
                for alias in node.names:
                    if alias.name == leaf:
                        names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == dotted:
                    names.add(alias.asname or alias.name.split(".")[0])
    return names


def _call_target(node: ast.Call) -> Tuple[Optional[str], Optional[str]]:
    """``(квалификатор, имя)`` вызова: ``base._run`` → ``('base', '_run')``."""
    func = node.func
    if isinstance(func, ast.Name):
        return None, func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id, func.attr
    if isinstance(func, ast.Attribute):
        return None, func.attr
    return None, None


# ------------------------------------------------- происхождение ЗНАЧЕНИЯ
#
# Правило живёт ЗДЕСЬ в единственном экземпляре, потому что здесь же живёт
# правило двери, которое его спрашивает. Сосед (`hand_truncation_census`)
# ВВОЗИТ обе функции: две копии одного правила разошлись бы молча, и та из
# них, что ошибается в сторону молчания, молчанием бы и осталась (ADR-418).

#: Имена, чей вызов превращает текст в КОЛЛЕКЦИЮ.
SPLITTERS = frozenset({"splitlines", "split", "rsplit", "readlines"})
LOADERS = frozenset({"loads", "load"})


def derives_from(expr: ast.AST, known: Set[str]) -> bool:
    """Происходит ли ЗНАЧЕНИЕ выражения от одного из имён ``known``.

    Контейнер производной НЕ является: ``{"out": proc.stdout}`` не делает
    значение выводом (`.claude/rules/deployment.md`, авария 2026-08-04). Иначе
    «RHS содержит якорь» оправдало бы ровно ту бомбу, против которой правило.

    Вызов ЧУЖОЙ функции с производным аргументом (``parse(out)``) производной
    тоже не считается — кроме поимённых разделителей и загрузчиков выше.
    Ошибка здесь односторонняя: непризнанное происхождение отнимает дверь и
    делает строку НАХОДКОЙ, то есть ошибается в сторону разговора, а не
    молчания.
    """
    if isinstance(expr, ast.Name):
        return expr.id in known
    if isinstance(expr, ast.Attribute):
        return derives_from(expr.value, known)
    if isinstance(expr, ast.Subscript):
        return derives_from(expr.value, known)
    if isinstance(expr, ast.Await):
        return derives_from(expr.value, known)
    if isinstance(expr, ast.BoolOp):
        return any(derives_from(v, known) for v in expr.values)
    if isinstance(expr, ast.BinOp):
        return derives_from(expr.left, known) or derives_from(expr.right, known)
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Attribute) and derives_from(func.value, known):
            return True
        _, fname = _call_target(expr)
        if fname in LOADERS or fname in SPLITTERS:
            return any(derives_from(a, known) for a in expr.args)
        return False
    if isinstance(expr, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        return any(derives_from(gen.iter, known) for gen in expr.generators)
    return False


def target_names(target: ast.AST) -> List[str]:
    """Имена, которым присваивает цель: ``a``, ``a, b`` — но не ``d["k"]``."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: List[str] = []
        for elt in target.elts:
            out.extend(target_names(elt))
        return out
    return []


def derived_names(func: ast.AST, *anchors: str) -> Set[str]:
    """Имена, чьё значение происходит от якорей — до неподвижной точки.

    Обход ограничен сверху не ради скорости, а ради завершимости: цикл
    связываний (``a = b`` / ``b = a``) иначе крутился бы вечно. Предел взят с
    запасом, и сходимость проверяется отдельным условием, а не надеждой.
    """
    known: Set[str] = {a for a in anchors if a}
    if not known:
        return known
    for _ in range(12):
        grew = False
        for node in ast.walk(func):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not derives_from(value, known):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in target_names(target):
                    if name not in known:
                        known.add(name)
                        grew = True
        if not grew:
            break
    return known


# -------------------------------------------------------------------- бюджет

def _module_int_consts(tree: ast.AST) -> Dict[str, Optional[int]]:
    """Целые константы уровня модуля — материал для разрешения ``keep=ИМЯ``."""
    out: Dict[str, Optional[int]] = {}
    body = tree.body if isinstance(tree, ast.Module) else []
    for node in body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant):
            value = node.value.value
            if isinstance(value, int) or value is None:
                out[node.targets[0].id] = value
    return out


def runner_default_budget(root: Path) -> int:
    """Умолчание бюджета — ИЗ модуля проводки, а не из копии здесь."""
    path = Path(root) / RUNNER_MODULE
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"модуль проводки не прочитан: {path} ({exc})") from exc
    value = _module_int_consts(tree).get(RUNNER_BUDGET_NAME)
    if not isinstance(value, int) or isinstance(value, bool):
        raise NotMeasured(
            f"{RUNNER_BUDGET_NAME} не сводится к целому в {RUNNER_MODULE}")
    return value


#: Бюджет, не сводимый статикой к числу. Отдельное значение, а не `None`:
#: `None` здесь ЗНАЧИТ «обрезания нет», и слить их значило бы выдать
#: неизмеренное за самый спокойный исход.
BUDGET_UNRESOLVED = "unresolved"


def site_budget(node: ast.Call, consts: Dict[str, Optional[int]], default):
    """Бюджет, действующий на ЭТОМ вызове."""
    for kw in node.keywords:
        if kw.arg != "keep":
            continue
        if isinstance(kw.value, ast.Constant):
            value = kw.value.value
            if value is None or (isinstance(value, int)
                                 and not isinstance(value, bool)):
                return value
            return BUDGET_UNRESOLVED
        if isinstance(kw.value, ast.Name) and kw.value.id in consts:
            return consts[kw.value.id]
        return BUDGET_UNRESOLVED
    return default


# ----------------------------------------------------------------- род чтения

def _is_splitlines(expr: ast.AST) -> bool:
    return (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)
            and expr.func.attr == "splitlines")


def iterates_lines(node: ast.AST) -> bool:
    """Обходит ли узел строки вывода С НАКОПЛЕНИЕМ.

    Обход с ``break`` (поиск сводки) перечнем не является: он читает ОДНУ
    строку, и обрезание её не уносит, потому что режется голова.
    """
    for sub in ast.walk(node):
        if isinstance(sub, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            if any(_is_splitlines(gen.iter) for gen in sub.generators):
                return True
        if isinstance(sub, ast.For) and _is_splitlines(sub.iter):
            for inner in ast.walk(sub):
                if isinstance(inner, ast.Call) \
                        and isinstance(inner.func, ast.Attribute) \
                        and inner.func.attr == "append":
                    return True
    return False


def reading_kind(body: ast.AST) -> str:
    """Род чтения тела: ПЕРЕЧЕНЬ (``list_read``) или ХВОСТ (``tail_read``)."""
    return READ_LIST if iterates_lines(body) else READ_TAIL


DOOR_NAMED = "door_named"
DOOR_COUNT = "door_count"


def door_evidence(body: ast.AST, origin: Set[str]) -> Tuple[Optional[str], List[dict]]:
    """Дверь тела — и ОТКЛОНЁННЫЕ сверки, каждая с причиной.

    Требование к ``door_count`` сужено заказом G51 (ADR-428, «чего решение не
    доказывает», п. 4): сверяемое ``len(X)`` обязано читать длину того, что
    ПРОИСХОДИТ от вывода. Прежнее правило засчитывало ЛЮБУЮ сверку ``len(...)``
    в теле — в том числе длины КОМАНДЫ, к перечню отношения не имеющей, — и
    ошибалось в сторону молчания: ложная дверь превращает находку в `guarded`.

    Отклонённая сверка не исчезает: она возвращается перечнем и попадает в
    строку переписи. Сужение, которое нельзя перемерить, есть та же ложная
    дверь, только с другой стороны.
    """
    for sub in ast.walk(body):
        if isinstance(sub, ast.Call) and _call_target(sub)[1] == TRUNCATION_DOOR:
            return DOOR_NAMED, []
    known = derived_names(body, *sorted(origin))
    declined: List[dict] = []
    for sub in ast.walk(body):
        if not isinstance(sub, ast.Compare):
            continue
        for side in [sub.left, *sub.comparators]:
            if not (isinstance(side, ast.Call)
                    and isinstance(side.func, ast.Name)
                    and side.func.id == "len"
                    and side.args):
                continue
            if derives_from(side.args[0], known):
                return DOOR_COUNT, []
            declined.append({
                "line": side.lineno,
                "measured": ast.unparse(side.args[0]),
                "reason": ("сверяется длина того, что от вывода не происходит"
                           if origin else
                           "якорь вывода в этом теле не назван: сопоставить "
                           "аргумент с параметром читателя не удалось"),
            })
    return None, declined


def has_door(body: ast.AST, origin: Set[str]) -> Optional[str]:
    """Есть ли у тела дверь, различающая «кончилось» и «обрезали»."""
    return door_evidence(body, origin)[0]


# ------------------------------------------------------------------ население

class ModuleIndex:
    """Разобранный файл: функции, константы, имена проводки."""

    def __init__(self, rel: str, tree: ast.Module):
        self.rel = rel
        self.tree = tree
        self.aliases = alias_map(tree)
        self.consts = _module_int_consts(tree)
        self.funcs: Dict[str, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs.setdefault(node.name, node)

    def is_runner_call(self, node: ast.Call) -> bool:
        qual, name = _call_target(node)
        if name != RUNNER_FUNC:
            return False
        if qual is None:
            return self.rel == RUNNER_MODULE
        return qual in self.aliases


def wrapper_budget(index: ModuleIndex, func: ast.AST, default):
    """Обёртка — функция, чьё тело ВОЗВРАЩАЕТ вызов проводки.

    Возврат: бюджет обёртки либо ``False`` — «не обёртка». Глубина ОДНА, и это
    объявлено: обёртка обёртки правилу не видна.
    """
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call) \
                and index.is_runner_call(node.value):
            return site_budget(node.value, index.consts, default)
    return False


def bound_text_name(stmt: ast.AST) -> Optional[str]:
    """Имя, которому присвоен ТЕКСТ прогона.

    Проводка возвращает ``(код, текст)``. Распаковка кортежа — вторая позиция;
    одиночная цель — само имя.
    """
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if isinstance(target, ast.Tuple) and len(target.elts) == 2 \
            and isinstance(target.elts[1], ast.Name):
        return target.elts[1].id
    if isinstance(target, ast.Name):
        return target.id
    return None


def readers_of(name: str, scope: ast.AST) -> Tuple[List[Tuple[Optional[str], str, object]], bool]:
    """Куда уходит имя текста: читатели ``[(квалификатор, функция, место)]`` и
    признак «обход прямо здесь».

    Третий член — МЕСТО, на котором вывод вошёл в читателя: номер позиции либо
    имя ключевого слова. Без него якорь внутри тела читателя назвать нечем, а
    безымянный якорь обнулил бы правило двери у всех вынесенных читателей
    сразу (заказ G51).
    """
    readers: List[Tuple[Optional[str], str, object]] = []
    inline = False
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            for pos, arg in enumerate(node.args):
                if isinstance(arg, ast.Name) and arg.id == name:
                    qual, fname = _call_target(node)
                    if fname:
                        readers.append((qual, fname, pos))
            for kw in node.keywords:
                if kw.arg and isinstance(kw.value, ast.Name) \
                        and kw.value.id == name:
                    qual, fname = _call_target(node)
                    if fname:
                        readers.append((qual, fname, kw.arg))
        if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.For)):
            if iterates_lines(node) and any(
                    isinstance(sub, ast.Name) and sub.id == name
                    for sub in ast.walk(node)):
                inline = True
    return readers, inline


def population(root: Path) -> List[Path]:
    """Файлы населения: ``spa_core/`` и ``scripts/``, без тестов."""
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


#: Читатели, чьё тело в населении не лежит и лежать не может: встроенные
#: имена и печать. Обрезание у них ничего не РЕШАЕТ — они не производят
#: вердикта, — поэтому они не «не измерено», а хвост. Перечень закрытый:
#: открытый список исключений лечил бы поводы, а не класс.
_NON_DECIDING_READERS = frozenset({
    "print", "len", "str", "repr", "bool", "strip", "format",
})


def module_alias_map(tree: ast.AST, rel_by_dotted: Dict[str, str]) -> Dict[str, str]:
    """Алиас → путь модуля населения, для ЛЮБОГО модуля населения.

    Нужен, чтобы разрешить читателя, живущего в соседнем файле
    (``vgp.failed_tests``): имя функции без модуля неоднозначно, а разбор по
    тексту выдумал бы находку.
    """
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                if dotted in rel_by_dotted:
                    out[alias.asname or alias.name] = rel_by_dotted[dotted]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in rel_by_dotted:
                    out[alias.asname or alias.name.split(".")[0]] = \
                        rel_by_dotted[alias.name]
    return out


def _enclosing_functions(tree: ast.Module) -> List[Tuple[str, ast.AST]]:
    """``(имя, узел)`` всех функций модуля. Модульный уровень — ``<module>``."""
    out: List[Tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node))
    return out


def _resolve_body(qual: Optional[str], fname: str, index: ModuleIndex,
                  indexes: Dict[str, ModuleIndex],
                  aliases: Dict[str, str]) -> Tuple[Optional[ast.AST], str]:
    """Тело читателя: свой модуль, соседний по алиасу — либо причина отказа."""
    if qual is None:
        body = index.funcs.get(fname)
        if body is not None:
            return body, ""
        if fname in _NON_DECIDING_READERS:
            return None, "non_deciding"
        return None, f"читатель `{fname}` не найден в {index.rel}"
    target = aliases.get(qual)
    if target is None:
        if fname in _NON_DECIDING_READERS:
            return None, "non_deciding"
        return None, f"модуль алиаса `{qual}` вне населения"
    other = indexes.get(target)
    if other is None:
        return None, f"модуль `{target}` не разобран"
    body = other.funcs.get(fname)
    if body is None:
        if fname in _NON_DECIDING_READERS:
            return None, "non_deciding"
        return None, f"читатель `{qual}.{fname}` не найден в {target}"
    return body, ""


def anchor_in_reader(body: ast.AST, place: object) -> Optional[str]:
    """Имя параметра, которым вывод вошёл в тело читателя.

    ``None`` — сопоставить не удалось (``*args``, звёздочка, чужая форма). Это
    НЕ «двери нет»: это «якорь не назван», и отличать одно от другого
    обязательно, иначе неизмеренное уехало бы под видом самого спокойного
    ответа (инв. #17). Причина доезжает до строки переписи.
    """
    args = getattr(body, "args", None)
    if args is None:
        return None
    if isinstance(place, str):
        for arg in [*args.args, *args.kwonlyargs, *getattr(args, "posonlyargs", [])]:
            if arg.arg == place:
                return place
        return None
    positional = [*getattr(args, "posonlyargs", []), *args.args]
    if isinstance(place, int) and 0 <= place < len(positional):
        return positional[place].arg
    return None


def classify_site(budget, consumption: str, door: Optional[str]) -> str:
    """Вердикт одного вызова.

    Порядок ветвей существен: «не измерено» спрашивается ПЕРВЫМ, иначе
    неразобранный бюджет молча получил бы самый спокойный ярлык.
    """
    if budget == BUDGET_UNRESOLVED or consumption == CLASS_UNMEASURED:
        return CLASS_UNMEASURED
    if budget is None:
        return CLASS_UNBOUNDED
    if consumption != READ_LIST:
        return CLASS_TAIL_SAFE
    return CLASS_GUARDED if door else CLASS_SILENT


def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    """Перепись: каждый ВЫЗОВ проводки ложится ровно в одну корзину."""
    root = Path(root)
    files = population(root)
    default_budget = runner_default_budget(root)

    rel_by_dotted: Dict[str, str] = {}
    indexes: Dict[str, ModuleIndex] = {}
    unreadable: List[dict] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            unreadable.append({"module": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        indexes[rel] = ModuleIndex(rel, tree)
        rel_by_dotted[rel[:-3].replace("/", ".")] = rel

    rows: List[dict] = []
    deep_wrappers: List[str] = []

    for rel, index in sorted(indexes.items()):
        aliases = module_alias_map(index.tree, rel_by_dotted)
        # Обёртки СВОЕГО модуля: имя → бюджет. Глубина одна.
        wrappers: Dict[str, object] = {}
        for name, func in _enclosing_functions(index.tree):
            budget = wrapper_budget(index, func, default_budget)
            if budget is not False:
                wrappers[name] = budget

        for enclosing, func in _enclosing_functions(index.tree):
            for stmt in ast.walk(func):
                if not isinstance(stmt, ast.Assign) \
                        or not isinstance(stmt.value, ast.Call):
                    continue
                call = stmt.value
                qual, fname = _call_target(call)
                via = ""
                if index.is_runner_call(call):
                    budget = site_budget(call, index.consts, default_budget)
                elif qual is None and fname in wrappers and fname != enclosing:
                    budget, via = wrappers[fname], fname
                elif qual is not None and aliases.get(qual) in indexes:
                    other = indexes[aliases[qual]]
                    other_wrappers = {
                        n: wrapper_budget(other, f, default_budget)
                        for n, f in _enclosing_functions(other.tree)}
                    value = other_wrappers.get(fname, False)
                    if value is False:
                        continue
                    budget, via = value, f"{qual}.{fname}"
                else:
                    continue

                text = bound_text_name(stmt)
                if text is None:
                    form = type(stmt.targets[0]).__name__ if stmt.targets else "?"
                    rows.append({
                        "module": rel, "enclosing": enclosing, "line": call.lineno,
                        "via_wrapper": via, "budget": budget,
                        "consumption": CLASS_UNMEASURED, "door": "",
                        "verdict": CLASS_UNMEASURED,
                        "reason": (
                            f"текст связан формой `{form}` (не имя и не пара "
                            f"«код, текст»): значение уходит в хранилище, а "
                            f"перенос между операторами правилу не виден"),
                        "readers": []})
                    continue

                found, inline = readers_of(text, func)
                consumption = READ_LIST if inline else READ_NONE
                reason = ""
                # Якорь ЗДЕСЬ — имя, которому связан текст прогона; дверь
                # засчитывается только той сверке, что читает длину его
                # производной (заказ G51 п. 3).
                here = {text}
                declined: List[dict] = []
                if inline:
                    door, refused = door_evidence(func, here)
                    declined.extend(refused)
                else:
                    door = None
                reader_names: List[str] = []
                for rqual, rname, place in found:
                    reader_names.append(f"{rqual}.{rname}" if rqual else rname)
                    body, why = _resolve_body(rqual, rname, index, indexes, aliases)
                    if body is None:
                        if why == "non_deciding":
                            if consumption == READ_NONE:
                                consumption = READ_TAIL
                            continue
                        consumption, reason = CLASS_UNMEASURED, why
                        break
                    kind = reading_kind(body)
                    if kind == READ_LIST:
                        consumption = READ_LIST
                        if door:
                            continue
                        param = anchor_in_reader(body, place)
                        inside, refused = door_evidence(
                            body, {param} if param else set())
                        declined.extend(refused)
                        door = inside
                        if not door:
                            outside, refused = door_evidence(func, here)
                            declined.extend(refused)
                            door = outside
                    elif consumption == READ_NONE:
                        consumption = READ_TAIL

                rows.append({
                    "module": rel, "enclosing": enclosing, "line": call.lineno,
                    "via_wrapper": via, "budget": budget,
                    "consumption": consumption, "door": door or "",
                    "door_declined": [] if door else declined,
                    "verdict": classify_site(budget, consumption, door),
                    "reason": reason, "readers": sorted(set(reader_names))})

        # Ширина слепоты правила глубины: обёртка, зовущая обёртку.
        for name, func in _enclosing_functions(index.tree):
            if name in wrappers:
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
                    q, f = _call_target(node.value)
                    if q is None and f in wrappers:
                        deep_wrappers.append(f"{rel}::{name}")

    # ПОРЯДОК строк — утверждение, а не косметика: отчёт усекается, усечение
    # режет хвост, значит голова обязана нести сильнейшее свидетельство.
    order = {CLASS_SILENT: 0, CLASS_UNMEASURED: 1, CLASS_GUARDED: 2,
             CLASS_UNBOUNDED: 3, CLASS_TAIL_SAFE: 4}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), r["module"], r["line"]))
    counts = {cls: sum(1 for r in rows if r["verdict"] == cls)
              for cls in (CLASS_SILENT, CLASS_GUARDED, CLASS_TAIL_SAFE,
                          CLASS_UNBOUNDED, CLASS_UNMEASURED)}
    counts["unreadable"] = len(unreadable)
    # Цена сужения правила двери — число, а не обещание: сверки `len(...)`,
    # которые ПРЕЖНЕЕ правило засчитало бы дверью, а это — нет.
    counts["door_declined"] = sum(len(r.get("door_declined") or []) for r in rows)
    findings = [r for r in rows if r["verdict"] in FINDING_CLASSES]
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "FINDING" if findings else "CLEAN",
        "question": "у какого зовущего общей проводки прогонов вход обрезается МОЛЧА",
        "population_rule": (
            f"spa_core/ + scripts/, без тестов; в население входит ВЫЗОВ "
            f"{RUNNER_MODULE}::{RUNNER_FUNC} — прямой либо через обёртку "
            f"глубины 1 (функция, чьё тело возвращает такой вызов). Ввоз "
            f"разбирается AST, не текстом"
        ),
        "runner": {"module": RUNNER_MODULE, "func": RUNNER_FUNC,
                   "default_budget": default_budget,
                   "doors": [DOOR_NAMED, DOOR_COUNT],
                   "door_count_rule": (
                       "сверяемое len(X) засчитывается дверью, только если X "
                       "ПРОИСХОДИТ от вывода (заказ G51 п. 3): длина команды "
                       "или чужого перечня дверью не является. Отклонённые "
                       "сверки названы построчно в door_declined")},
        "scanned": len(files),
        "call_sites": len(rows),
        "counts": counts,
        "rows": rows,
        "unreadable": unreadable,
        # Ширина слепоты правила глубины — число, а не обещание.
        "wrapper_depth_exceeded": sorted(set(deep_wrappers)),
        "what_it_does_not_prove": [
            "что обрезание произошло СЕГОДНЯ: длина вывода — свойство машины, "
            "а не дерева; прибор читает, может ли потеря случиться молча",
            "что tail_safe читает свой хвост ВЕРНО — род чтения не есть верность разбора",
            "что отклонённая сверка НЕ была дверью по сути: правило "
            "происхождения не признаёт вызов чужой функции с производным "
            "аргументом, и ошибается оно в сторону находки, а не молчания",
            "что население полно: глубина обёрток одна, ширина названа "
            "wrapper_depth_exceeded",
            "что у silent_truncation уже есть вред: вред требует, чтобы вывод "
            "однажды перерос бюджет",
        ],
    }


def report(doc: dict, *, max_rows: int = 20) -> List[str]:
    """Строки отчёта. Единственное место, где перепись становится текстом."""
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — "
                f"{observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    runner = observed(doc, "runner", kind=dict) or {}
    classified = sum(counts.get(c, 0) for c in
                     (CLASS_SILENT, CLASS_GUARDED, CLASS_TAIL_SAFE,
                      CLASS_UNBOUNDED, CLASS_UNMEASURED))
    out = [
        f"обрезан ли вход у зовущего проводки (заказ G49 п. 2): {status} · "
        f"вызовов {doc.get('call_sites')} · ОБРЕЗАЕТСЯ МОЛЧА "
        f"{counts.get(CLASS_SILENT)} · с дверью {counts.get(CLASS_GUARDED)} · "
        f"хвост {counts.get(CLASS_TAIL_SAFE)} · без бюджета "
        f"{counts.get(CLASS_UNBOUNDED)} · не измерено {counts.get(CLASS_UNMEASURED)}"
        f" · сверок отклонено {counts.get('door_declined')}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[ПРОВОДКА] {runner.get('module')}::{runner.get('func')} · умолчание "
        f"бюджета {runner.get('default_budget')} знак(ов) · режется ГОЛОВА",
        f"[УЧЁТ] осмотрено файлов {doc.get('scanned')} · вызовов "
        f"{doc.get('call_sites')} = разобрано {classified} + не разобрано "
        f"{counts.get('unreadable')}",
    ]
    findings = [r for r in (doc.get("rows") or [])
                if r["verdict"] in FINDING_CLASSES]
    for row in findings[:max_rows]:
        via = f" (через {row['via_wrapper']})" if row.get("via_wrapper") else ""
        out.append(
            f"[НАХОДКА] {row['module']}:{row['line']} `{row['enclosing']}`{via}: "
            f"читает ПЕРЕЧЕНЬ при бюджете {row['budget']} и без двери — "
            f"читатели: {', '.join(row['readers']) or '— тут же'}")
    if len(findings) > max_rows:
        # Умолчание об укорочении и есть способ соврать усечением.
        out.append(f"[…] показаны {max_rows} находки из {len(findings)}; "
                   f"полный перечень — в артефакте")
    unmeasured = [r for r in (doc.get("rows") or [])
                  if r["verdict"] == CLASS_UNMEASURED]
    for row in unmeasured[:5]:
        out.append(f"[НЕ ИЗМЕРЕНО] {row['module']}:{row['line']} "
                   f"`{row['enclosing']}` — {row.get('reason') or 'причина не записана'}")
    # Цена сужения правила двери — поимённо, а не только числом: сверка,
    # которую ПРЕЖНЕЕ правило засчитало бы дверью, обязана быть названа, иначе
    # сужение проверить нечем.
    for row in (doc.get("rows") or []):
        for item in (row.get("door_declined") or [])[:2]:
            out.append(f"[СВЕРКА НЕ ДВЕРЬ] {row['module']}:{item['line']} "
                       f"`{row['enclosing']}` — len({item['measured']}): "
                       f"{item['reason']}")
    deep = doc.get("wrapper_depth_exceeded") or []
    out.append(f"[ГРАНИЦА ПРАВИЛА ГЛУБИНЫ] обёрток над обёрткой: {len(deep)}"
               + (f" — {', '.join(deep[:5])}" if deep else ""))
    out.append("НЕ ДОКЛАДЫВАЕТ: произошло ли обрезание сегодня (длина вывода — "
               "свойство машины); верно ли tail_safe читает свой хвост; была "
               "ли отклонённая сверка дверью ПО СУТИ — правило происхождения "
               "ошибается в сторону находки, а не молчания")
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
    секунды (та же причина, что у ``tact_gate_census``, ADR-415). Недельный
    такт не купил бы ничего, а завёл бы вторую копию правила срока.
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
        description="перепись обрезанного входа у зовущих общей проводки (G49 п. 2)")
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
