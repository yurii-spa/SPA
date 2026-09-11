"""Сколько утверждений судят о СТРУКТУРЕ по ПОДСТРОКЕ её сериализованного вида.

Заказ #567 (стоячая карточка CIO `inbox-task-portfolio-cio-dynamic-capital-alloc`)
поставлен дословно так:

> Найденное в #567 — про ФОРМУ утверждения, а не про схему: тест утверждал
> структуру соседа **подстрокой её текста**, и подстрока по построению не знает,
> что стои́т ЗА ней. Вопрос: **сколько ещё утверждений в наборе судят о СТРУКТУРЕ
> (словаре, кортеже, списке, записи json/yaml) по ПОДСТРОКЕ её сериализованного
> вида — и у скольких из них эта подстрока обрывается до конца структуры?**
> Первым результатом обязано быть НАСЕЛЕНИЕ: сколько ``assertIn`` /
> ``assertTrue(... in ...)`` / ``self.assertIn(<литерал>, <текст файла>)`` имеют
> левым аргументом литерал, СИНТАКСИЧЕСКИ похожий на начало структуры (открытая
> скобка без закрывающей, запятая на конце, двоеточие внутри). Ноль ⇒ третий
> исход «класс одиночный», закрытый замером.
>
> Ловушка названа заранее, и она ровно та же, что там: соблазн — грепать
> ``assertIn`` и объявить долю. Это ответ на другой вопрос, потому что
> ``assertIn`` по СПИСКУ КЛЮЧЕЙ не есть дефект вовсе — дефект у того, кто ищет
> подстроку в ТЕКСТЕ, и только если литерал обрывает структуру. Отделить эти два
> случая надо ЗАМЕРОМ (правый аргумент — результат чтения файла? левый —
> незакрытая структура?), а не глазами; и сказать это надо ПРЕЖДЕ, чем называть
> долю. Вторая ловушка: «обрывается» проверяется не на глаз, а воспроизведением —
> дописать в структуру соседа лишний элемент ЗА концом литерала и померить,
> изменился ли вердикт. Не удалось возмутить ⇒ ``unmeasured`` с названной
> причиной, НЕ ``stable``.

## Что случилось в #567 и почему вопрос не праздный

Приёмка прибора ADR-333 утверждала схему шага 0-офис так::

    self.assertIn('"subject_population_census.json": ("status", "counts",', src)

Слева — начало кортежа, справа — ТЕКСТ соседнего скрипта. Снятие ключа
``blindness`` из этого кортежа оставляло тест ЗЕЛЁНЫМ: подстрока обрывается на
``"counts",`` и о том, что стои́т за ней, не знает ничего. Это буквально тот
дефект, ради которого прибор и писался, — живущий внутри его собственной
приёмки.

## Три числа, и ни одно не выводится из другого

``население``  сколько утверждений ищут литерал-«начало структуры» в ТЕКСТЕ,
               прочитанном из исходника соседа.
``обрыв``      у скольких из них литерал обрывается до конца структуры — и это
               ДОКАЗАНО возмущением, а не заподозрено по виду.
``род стога``  сколько утверждений ищут тот же литерал в КОНТЕЙНЕРЕ (список
               ключей, словарь, множество). Это НЕ дефект и складывать его с
               населением нельзя: ``assertIn(key, d)`` спрашивает о членстве в
               структуре, а не о подстроке её текста.

Первое не есть обвинение. Литерал, покрывающий структуру ЦЕЛИКОМ, обрывом не
является, и утверждение о нём верно.

## Обрыв меряется ВОЗМУЩЕНИЕМ, а не по виду литерала

Статический признак («скобка не закрыта») — это ПРИЗНАК, и у признака нет права
быть ответом: ровно на подмене признака ответом погорел ADR-326. Поэтому обрыв
здесь — ЗАМЕР:

1. найти в исходнике соседа место совпадения литерала;
2. разобрать соседа в AST и найти ТУ САМУЮ структуру (``dict``/``tuple``/
   ``list``/``set``/зов), внутрь которой попало совпадение;
3. удалить из неё ПОСЛЕДНИЙ элемент, лежащий ЦЕЛИКОМ ЗА концом литерала;
4. перечитать предикат утверждения на возмущённом тексте.
   **Вердикт не изменился ⇒ утверждение СЛЕПО к удалённому элементу**, то есть
   подстрока обрывается до конца структуры, и это доказано.

Почему это не «истинно по построению». Оба исхода достижимы и оба наблюдаются:
литерал, покрывающий структуру до конца, элемента за своим концом не имеет
вовсе — возмущать нечего, и сайт получает ``stable`` с названной причиной; а
литерал, оборвавшийся на середине, оставляет предикат истинным при удалении
элемента, которого он не видит. Между ними проходит вся разница вопроса.

Возмущение применяется к КОПИИ текста в памяти. Ни один файл дерева прибором не
мутируется.

**Сцена обязана нарушать ТОЛЬКО своё ограничение.** Возмущённый текст
перепроверяется разбором: сломался синтаксис ⇒ это ``unmeasured`` с названной
причиной, а не вердикт об утверждении. Иначе замер докладывал бы о поломке
чужого файла как о слепоте соседа.

**Литерал, встречающийся у соседа НЕСКОЛЬКО раз, — тоже ``unmeasured``**, и это
важно: возмущение ОДНОЙ структуры не может перевернуть предикат, если рядом
лежит второе совпадение, — вердикт «слеп» получился бы по построению.

## Полнота населения — ОТДЕЛЬНОЕ утверждение, доказанное ВТОРОЙ дорогой

Счётчик, выведенный одной формой, о своей неполноте сказать не может. Поэтому
население выводится дважды и НЕЗАВИСИМО:

``A`` (точная)    разбор AST: зов-утверждение → строковый литерал слева →
                  пометка стога как текста, прочитанного из исходника соседа.
``B`` (полнотная) чистый текстовый обход по ФОРМЕ ЗОВА (``assertIn(``,
                  ``assertNotIn(``, ``assertTrue(``, ``assertFalse(``,
                  строка-``assert``). Про литералы и стога не знает ничего.

``B`` обязана быть НАДМНОЖЕСТВОМ по «файл + строка». Каждый остаток ``B \\ A``
получает НАЗВАННУЮ причину; остаток без причины — ТРЕТИЙ ИСХОД ``unmeasured``,
и он не складывается с нулём.

ADVISORY: прибор только читает исходники набора. Ни один тест не правится, не
скипается и не сужается; ``POLLED_ADAPTERS``, пины, писатель журнала решений,
пороги RiskPolicy v1.0, стоп-кран и живой трек не тронуты.
"""

from __future__ import annotations

import ast
import os
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from spa_core.monitoring.subject_population_census import (
    check_files,
    taint_source_names,
)

OUTPUT_FILENAME = "substring_structure_assertions.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Зовы-утверждения о ВХОЖДЕНИИ. `assertNotIn` входит намеренно: он о том же
#: предикате, только с другим ожидаемым вердиктом, и обрывается его литерал
#: ровно так же.
_MEMBERSHIP_ASSERTS = ("assertIn", "assertNotIn")
#: Зовы, у которых предикат вхождения лежит ВНУТРИ аргумента-сравнения.
_TRUTH_ASSERTS = ("assertTrue", "assertFalse")

#: Формы, по которым дорога B (полнотная) узнаёт строку-кандидата. Литералов и
#: стогов эта дорога не разбирает вовсе — в этом и смысл второй дороги.
_RECALL_FORMS = re.compile(
    r"(?:\.|\b)(assertIn|assertNotIn|assertTrue|assertFalse)\s*\(|^\s*assert\s")

#: Узлы, которые прибор считает СТРУКТУРОЙ: у них есть элементы, и элемент
#: может лежать за концом литерала.
_STRUCTURE_NODES = (ast.Dict, ast.List, ast.Tuple, ast.Set, ast.Call)


# ─────────────────────────── общее ───────────────────────────

def _rel(root: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(p)


def _line_starts(src: str) -> List[int]:
    """Байтовые смещения начала каждой строки.

    Смещения ИМЕННО байтовые: `ast.col_offset` — смещение в БАЙТАХ внутри
    строки, и символьная нарезка на кириллице съедает часть узла (урок цикла,
    закреплённый в памяти проекта). Весь замер поэтому идёт в байтах.
    """
    offs: List[int] = []
    pos = 0
    for line in src.splitlines(keepends=True):
        offs.append(pos)
        pos += len(line.encode("utf-8"))
    offs.append(pos)
    return offs


def _span(node: ast.AST, starts: List[int]) -> Optional[Tuple[int, int]]:
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    if lineno is None or end_lineno is None:
        return None
    if lineno - 1 >= len(starts) or end_lineno - 1 >= len(starts):
        return None
    return (starts[lineno - 1] + node.col_offset,
            starts[end_lineno - 1] + node.end_col_offset)


# ─────────────── форма литерала: «начало структуры?» ───────────────

def literal_markers(lit: str) -> List[str]:
    """Синтаксические признаки «литерал — начало структуры».

    Ровно три, названные заказом: открытая скобка без закрывающей, запятая на
    конце, двоеточие внутри. Признак — НЕ приговор: обрыв меряется возмущением.
    """
    markers: List[str] = []
    depth = 0
    quote: Optional[str] = None
    saw_colon = False
    for ch in lit:
        if quote is not None:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ":":
            saw_colon = True
    if depth > 0:
        markers.append("unclosed_bracket")
    if lit.rstrip().endswith(","):
        markers.append("trailing_comma")
    if saw_colon:
        markers.append("colon_inside")
    return markers


# ─────────────── род стога: ТЕКСТ или КОНТЕЙНЕР ───────────────

def _is_source_text(node: ast.AST, tainted: Set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("read_text", "getsource", "read"):
            return True
    if isinstance(node, ast.Attribute):
        return False
    return False


def _container_kind(node: ast.AST) -> Optional[str]:
    """Стог, который есть СТРУКТУРА, а не её текст. Это НЕ дефект."""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return "literal_container"
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("keys", "values", "items"):
            return "mapping_view"
        if isinstance(fn, ast.Name) and fn.id in ("set", "list", "tuple", "dict", "frozenset"):
            return "container_ctor"
    return None


def haystack_kind(node: ast.AST, tainted: Set[str]) -> str:
    if _is_source_text(node, tainted):
        return "text"
    kind = _container_kind(node)
    if kind is not None:
        return "container"
    return "unresolved"


# ─────────────────── дорога A: разбор AST ────────────────────

def _membership_pair(node: ast.AST) -> Optional[Tuple[ast.AST, ast.AST, str, bool]]:
    """Из узла достать (иголка, стог, форма зова, ОЖИДАЕТСЯ ЛИ ВХОЖДЕНИЕ).

    Знак предиката — не косметика. У `assertNotIn` укорочение литерала делает
    утверждение СТРОЖЕ, а не слепее: короткий префикс найти ЛЕГЧЕ, значит
    отрицание сработает ОХОТНЕЕ. Предмет заказа — положительная претензия;
    отрицательные считаются ПОРОЗНЬ и в обрыв не складываются.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        if attr in _MEMBERSHIP_ASSERTS and len(node.args) >= 2:
            return (node.args[0], node.args[1], attr, attr == "assertIn")
        if attr in _TRUTH_ASSERTS and node.args:
            cmp_node = node.args[0]
            if isinstance(cmp_node, ast.Compare) and len(cmp_node.ops) == 1 \
                    and isinstance(cmp_node.ops[0], (ast.In, ast.NotIn)):
                positive = isinstance(cmp_node.ops[0], ast.In) == (attr == "assertTrue")
                return (cmp_node.left, cmp_node.comparators[0], attr, positive)
    if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare) \
            and len(node.test.ops) == 1 \
            and isinstance(node.test.ops[0], (ast.In, ast.NotIn)):
        return (node.test.left, node.test.comparators[0], "assert",
                isinstance(node.test.ops[0], ast.In))
    return None


def forward_sites(root: Path) -> Tuple[List[dict], List[dict]]:
    """Все сайты-утверждения о вхождении (дорога A) и их разбор.

    Возвращает (население, все_сайты). Население — подмножество, у которого
    стог ТЕКСТОВЫЙ и литерал похож на начало структуры.
    """
    population: List[dict] = []
    every: List[dict] = []

    for check_file in check_files(root):
        try:
            src = check_file.read_text(encoding="utf-8", errors="replace")
            # Разбор ЧУЖОГО файла может поднять SyntaxWarning (битая escape-
            # последовательность в чужой строке). Это находка ПРО СОСЕДА, а не
            # про прибор, и засорять ею вывод замера нельзя.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError):
            continue
        tainted = taint_source_names(tree)
        origins = read_origins(tree)
        parents = parent_map(tree)
        fold = fold_env(tree, check_file, root)

        for node in ast.walk(tree):
            pair = _membership_pair(node)
            if pair is None:
                continue
            needle, hay, form, positive = pair
            site = {
                "file": _rel(root, check_file),
                "line": getattr(node, "lineno", 0),
                "form": form,
                "positive": positive,
            }
            if not positive:
                site["excluded"] = (
                    "предикат ОТРИЦАТЕЛЬНЫЙ: укорочение литерала делает такое "
                    "утверждение СТРОЖЕ, а не слепее — предмет заказа не этот")
                every.append(site)
                continue
            if not (isinstance(needle, ast.Constant) and isinstance(needle.value, str)):
                site["excluded"] = "слева не строковый литерал — судить о подстроке нечем"
                every.append(site)
                continue
            lit = needle.value
            site["literal"] = lit if len(lit) <= 200 else lit[:200] + "…"
            kind = haystack_kind(hay, tainted)
            site["haystack"] = kind
            if kind != "text":
                site["excluded"] = (
                    "стог — КОНТЕЙНЕР, а не текст: `assertIn(key, d)` спрашивает о "
                    "членстве в структуре, и дефектом не является"
                    if kind == "container" else
                    "род стога статикой не разрешён — ни текст чтения, ни контейнер")
                every.append(site)
                continue
            markers = literal_markers(lit)
            site["markers"] = markers
            if not markers:
                site["excluded"] = (
                    "литерал не несёт ни одного признака начала структуры "
                    "(скобка закрыта, запятой на конце нет, двоеточия нет)")
                every.append(site)
                continue
            neighbour = _haystack_file(hay, fold, origins, parents, node)
            if neighbour is None:
                site["excluded"] = (
                    "стог — текст файла, ПУТЬ которого статикой не свернулся "
                    "(временный каталог, фикстура, аргумент): судить о структуре "
                    "СОСЕДА тут не о чем, и приписать сайту вердикт значило бы "
                    "изготовить находку из неизмеренного")
                every.append(site)
                continue
            if neighbour.suffix not in _SOURCE_SUFFIXES or not neighbour.is_file():
                site["excluded"] = (
                    f"читаемый файл не исходник соседа под корнем дерева "
                    f"({neighbour.suffix or 'без расширения'}, "
                    f"{'существует' if neighbour.is_file() else 'НЕ существует'})")
                every.append(site)
                continue
            site["neighbour"] = _rel(root, neighbour)
            every.append(site)
            population.append(site)
    return population, every


#: Расширения, которые считаются ИСХОДНИКОМ соседа. Артефакт (`.json`) сюда не
#: входит намеренно: вопрос заказа — о ТЕКСТЕ кода, который несёт структуру.
_SOURCE_SUFFIXES = (".py", ".sh", ".yml", ".yaml", ".plist", ".toml", ".cfg", ".md")


def parent_map(tree: ast.Module) -> Dict[int, ast.AST]:
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def read_origins(tree: ast.Module) -> List[Tuple[str, ast.AST, ast.AST]]:
    """(имя, зов чтения, узел-присваивание) на ЛЮБОМ уровне вложенности.

    Сосед (`subject_population_census._read_origins`) собирает только модульный
    уровень, а в наборе `src = Path(...).read_text()` почти всегда стои́т ВНУТРИ
    метода. Замер по модульному словарю дал бы «соседа не назвали статикой» на
    сайтах, где он назван прямо — верный ответ не на тот вопрос.

    Плоского словаря «имя → зов» здесь НЕДОСТАТОЧНО и это измерено: в одном
    файле `src` присваивается в четырёх методах разными соседями, и плоский
    словарь отдал бы всем четырём ПОСЛЕДНЕГО — то есть приписал бы утверждению
    чужой файл. Поэтому происхождение разрешается ПО ОБЛАСТИ ВИДИМОСТИ.
    """
    out: List[Tuple[str, ast.AST, ast.AST]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        val = node.value
        if not (isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute)
                and val.func.attr in ("read_text", "read", "getsource")):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                out.append((tgt.id, val, node))
    return out


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)


def _scope_of(node: ast.AST, parents: Dict[int, ast.AST]) -> Optional[ast.AST]:
    cur: Optional[ast.AST] = node
    while cur is not None:
        if isinstance(cur, _SCOPES):
            return cur
        cur = parents.get(id(cur))
    return None


def scoped_read_origin(name: str, site: ast.AST, origins, parents) -> Optional[ast.AST]:
    """Зов чтения, давший `name` В ОБЛАСТИ ВИДИМОСТИ сайта.

    Берётся ПОСЛЕДНЕЕ присваивание выше сайта внутри ближайшей объемлющей
    функции; не нашлось — поднимаемся к модулю. Не нашлось нигде ⇒ `None`,
    и сайт получит НАЗВАННУЮ причину, а не чужого соседа.
    """
    site_line = getattr(site, "lineno", 0)
    scope = _scope_of(site, parents)
    chain: List[ast.AST] = []
    cur = scope
    while cur is not None:
        chain.append(cur)
        cur = _scope_of(parents.get(id(cur)), parents) if parents.get(id(cur)) else None
    for sc in chain:
        best = None
        best_line = -1
        for nm, call, assign in origins:
            if nm != name:
                continue
            if _scope_of(assign, parents) is not sc:
                continue
            line = getattr(assign, "lineno", 0)
            if line <= site_line and line > best_line:
                best, best_line = call, line
        if best is not None:
            return best
    return None


def import_module_files(tree: ast.Module, root: Path) -> Dict[str, Path]:
    """Локальное имя импортированного модуля → файл этого модуля.

    Разрешение идёт АРИФМЕТИКОЙ ПУТИ под корнем дерева, а не импортом: прибор
    обязан читать чужой набор, ничего в нём не исполняя.
    """
    out: Dict[str, Path] = {}

    def resolve(dotted: str) -> Optional[Path]:
        cand = root.joinpath(*dotted.split("."))
        if cand.with_suffix(".py").is_file():
            return cand.with_suffix(".py")
        if (cand / "__init__.py").is_file():
            return cand / "__init__.py"
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                got = resolve(alias.name)
                if got is not None:
                    out[alias.asname or alias.name.split(".")[0]] = got
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                got = resolve(f"{node.module}.{alias.name}")
                if got is not None:
                    out[alias.asname or alias.name] = got
    return out


def fold_env(tree: ast.Module, check_file: Path, root: Path):
    """Свёртка выражения-пути. Расширяет форму соседа на те, что реально в наборе.

    Сверх `path_folder`: `.parent`, `Path(<модуль>.__file__)` и присваивания на
    ЛЮБОМ уровне (модуль, класс, функция) — до неподвижной точки. Не свернулось
    — `None`, и сайт получает НАЗВАННУЮ причину, а не угаданный путь.
    """
    known: Dict[str, Path] = {}
    mod_files = import_module_files(tree, root)

    def fold(node: ast.AST) -> Optional[Path]:
        if isinstance(node, ast.Attribute):
            if node.attr == "parent":
                inner = fold(node.value)
                return inner.parent if inner is not None else None
            if node.attr == "__file__" and isinstance(node.value, ast.Name):
                return mod_files.get(node.value.id)
            return None
        if isinstance(node, ast.Name):
            return known.get(node.id)
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "Path" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Name) and a.id == "__file__":
                    return check_file
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    q = Path(a.value)
                    return q if q.is_absolute() else (root / a.value)
                return fold(a)
            if isinstance(fn, ast.Attribute) and fn.attr in ("resolve", "absolute"):
                return fold(fn.value)
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = fold(node.left)
            if left is not None and isinstance(node.right, ast.Constant) \
                    and isinstance(node.right.value, str):
                return left / node.right.value
            return None
        if isinstance(node, ast.Subscript):
            b = node.value
            if isinstance(b, ast.Attribute) and b.attr == "parents":
                anchor = fold(b.value)
                idx = node.slice
                if anchor is not None and isinstance(idx, ast.Constant) \
                        and isinstance(idx.value, int):
                    parents = anchor.resolve().parents
                    if idx.value < len(parents):
                        return parents[idx.value]
            return None
        return None

    # присваивания-пути на ЛЮБОМ уровне, до неподвижной точки
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    for _ in range(4):
        grew = False
        for node in assigns:
            folded = fold(node.value)
            if folded is None:
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and known.get(tgt.id) != folded:
                    known[tgt.id] = folded
                    grew = True
        if not grew:
            break
    return fold


def _haystack_file(node: ast.AST, fold, origins, parents, site,
                   seen: Optional[Set[int]] = None) -> Optional[Path]:
    """Какой файл читает стог. Не свернулось — None (сайт получит причину)."""
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return None
    seen.add(id(node))
    if isinstance(node, ast.Name):
        origin = scoped_read_origin(node.id, site, origins, parents)
        return (_haystack_file(origin, fold, origins, parents, site, seen)
                if origin is not None else None)
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("read_text", "read"):
            return fold(fn.value)
        if isinstance(fn, ast.Attribute) and fn.attr == "getsource" and node.args:  # noqa: E501
            return fold(ast.Attribute(value=node.args[0], attr="__file__",
                                      ctx=ast.Load()))
    return None


# ─────────────── замер обрыва: ВОЗМУЩЕНИЕ соседа ───────────────

def _elements(node: ast.AST) -> List[ast.AST]:
    if isinstance(node, ast.Dict):
        out: List[ast.AST] = []
        for k, v in zip(node.keys, node.values):
            out.append(k if k is not None else v)
        return out
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return list(node.elts)
    if isinstance(node, ast.Call):
        return list(node.args) + [kw.value for kw in node.keywords]
    return []


def _pair_span(node: ast.Dict, idx: int, starts: List[int]) -> Optional[Tuple[int, int]]:
    """Span пары ключ-значение словаря (ключ может быть None у `**x`)."""
    key = node.keys[idx]
    val = node.values[idx]
    first = key if key is not None else val
    a = _span(first, starts)
    b = _span(val, starts)
    if a is None or b is None:
        return None
    return (a[0], b[1])


def truncation_probe(literal: str, neighbour: Path) -> dict:
    """Обрывается ли литерал до конца структуры — ЗАМЕРОМ.

    Третий исход `unmeasured` с названной причиной обязателен: «не удалось
    возмутить» не есть «устойчиво».
    """
    try:
        src = neighbour.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"verdict": "unmeasured",
                "reason": f"сосед не прочитан: {type(exc).__name__}"}

    src_b = src.encode("utf-8")
    lit_b = literal.encode("utf-8")
    hits = []
    at = src_b.find(lit_b)
    while at != -1:
        hits.append(at)
        at = src_b.find(lit_b, at + 1)
    if not hits:
        return {"verdict": "unmeasured",
                "reason": "литерал в разрешённом соседе НЕ найден — предмет "
                          "утверждения либо другой файл, либо сосед изменился"}
    if len(hits) > 1:
        return {"verdict": "unmeasured",
                "reason": f"литерал встречается у соседа {len(hits)} раз(а): "
                          "возмущение ОДНОЙ структуры не может перевернуть "
                          "предикат, и «слеп» получился бы по построению"}

    start, end = hits[0], hits[0] + len(lit_b)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(src)
    except (SyntaxError, ValueError) as exc:
        return {"verdict": "unmeasured",
                "reason": f"сосед не разбирается в AST: {type(exc).__name__}"}
    starts = _line_starts(src)

    # ВАЖНО: предмет — структура, которую литерал РАЗРЕЗАЕТ, то есть та, внутрь
    # которой попадает КОНЕЦ литерала. Брать «наименьшую, содержащую всё
    # совпадение» — ошибка первой редакции: у `{"a": ("x", "y", "z")}` она даёт
    # СЛОВАРЬ (кортеж не содержит ключа), у словаря ровно одна пара, та пара
    # концом литерала не покрыта, — и настоящий обрыв кортежа читался бы как
    # «литерал утверждает существование». Разрезаемая структура здесь — кортеж.
    best: Optional[ast.AST] = None
    best_span: Optional[Tuple[int, int]] = None
    for node in ast.walk(tree):
        if not isinstance(node, _STRUCTURE_NODES):
            continue
        span = _span(node, starts)
        if span is None:
            continue
        if span[0] < end < span[1]:
            if best_span is None or (span[1] - span[0]) < (best_span[1] - best_span[0]):
                best, best_span = node, span
    if best is None or best_span is None:
        return {"verdict": "unmeasured",
                "reason": "конец литерала не попадает внутрь структуры — литерал "
                          "лёг в текст соседа, а не разрезал словарь/кортеж/"
                          "список/зов"}

    # элементы, лежащие ЦЕЛИКОМ за концом литерала
    if isinstance(best, ast.Dict):
        spans = [(_pair_span(best, i, starts)) for i in range(len(best.values))]
    else:
        spans = [_span(e, starts) for e in _elements(best)]
    spans = [s for s in spans if s is not None]
    inside = [s for s in spans if s[1] <= end]
    if not inside:
        return {"verdict": "existence_only",
                "reason": "литерал обрывается ДО первого элемента структуры: он "
                          "утверждает СУЩЕСТВОВАНИЕ зова/структуры, а не её "
                          "содержимое — предмет заказа не этот",
                "structure": type(best).__name__}
    beyond = [s for s in spans if s[0] >= end]
    if not beyond:
        return {"verdict": "stable",
                "reason": "за концом литерала у структуры нет ни одного элемента "
                          "— литерал покрывает её до конца",
                "structure": type(best).__name__,
                "structure_end": best_span[1], "literal_end": end}

    victim = beyond[-1]
    before = [s for s in spans if s[1] <= victim[0]]
    # Резать НИКОГДА не внутрь литерала: разделитель, попавший в литерал (та
    # самая запятая на конце), принадлежит УТВЕРЖДЕНИЮ, а не удаляемому
    # элементу. Срезав его, замер сломал бы литерал и доложил «обрыва нет» —
    # то есть отвечал бы на вопрос о СВОЁМ разрезе, а не об утверждении.
    cut_from = max(before[-1][1], end) if before else max(victim[0], end)
    perturbed_b = src_b[:cut_from] + src_b[victim[1]:]
    try:
        perturbed = perturbed_b.decode("utf-8")
    except UnicodeDecodeError:
        return {"verdict": "unmeasured",
                "reason": "возмущение разрезало многобайтовый символ — замер "
                          "нарушил бы не только своё ограничение"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            ast.parse(perturbed)
    except (SyntaxError, ValueError):
        return {"verdict": "unmeasured",
                "reason": "возмущение сломало синтаксис соседа: сцена нарушила бы "
                          "не ТОЛЬКО своё ограничение, и вердикт о ней ничего не "
                          "говорит об утверждении"}

    still = lit_b in perturbed_b
    return {
        "verdict": "truncating" if still else "stable",
        "reason": ("вердикт НЕ изменился после удаления элемента за концом "
                   "литерала — утверждение к нему СЛЕПО"
                   if still else
                   "вердикт изменился: удаление элемента за концом литерала "
                   "ломает утверждение — обрыва нет"),
        "structure": type(best).__name__,
        "elements_beyond_literal": len(beyond),
        "structure_end": best_span[1], "literal_end": end,
    }


# ─────────────── дорога B: полнотная, по форме зова ───────────────

def recall_lines(root: Path) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for check_file in check_files(root):
        try:
            src = check_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _rel(root, check_file)
        for i, line in enumerate(src.splitlines(), start=1):
            if _RECALL_FORMS.search(line):
                out.append((rel, i))
    return out


def _residue_reason(every_by_anchor: Dict[Tuple[str, int], dict],
                    anchor: Tuple[str, int]) -> str:
    site = every_by_anchor.get(anchor)
    if site is None:
        return "строка не несёт зова-утверждения о вхождении на уровне AST " \
               "(комментарий, строка, другой предикат, перенос зова)"
    return site.get("excluded") or "сайт разобран, но в население не попал без причины"


# ─────────────────────────── замер ───────────────────────────

def measure(root: Path, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    root = Path(root)

    population, every = forward_sites(root)

    # ─ обрыв меряется возмущением ─
    truncating: List[dict] = []
    stable: List[dict] = []
    unmeasured: List[dict] = []
    existence_only: List[dict] = []
    for site in population:
        nb = site.get("neighbour")
        if not nb:
            probe = {"verdict": "unmeasured",
                     "reason": "путь читаемого соседа статикой не свернулся — "
                               "возмущать нечего, и это ТРЕТИЙ исход, не «устойчиво»"}
        else:
            probe = truncation_probe(site["literal"], root / nb)
        site["probe"] = probe
        {"truncating": truncating, "stable": stable,
         "existence_only": existence_only}.get(
            probe["verdict"], unmeasured).append(site)

    # ─ род стога считается ПОРОЗНЬ: это не дефект ─
    kinds: Dict[str, int] = {}
    for site in every:
        kinds[site.get("haystack", "no_literal")] = \
            kinds.get(site.get("haystack", "no_literal"), 0) + 1

    # ─ отвод: текстовый стог, у которого сосед не назван статикой ─
    excluded_classes: Dict[str, int] = {}
    for site in every:
        why = site.get("excluded")
        if why:
            excluded_classes[why] = excluded_classes.get(why, 0) + 1
    text_without_neighbour = sum(
        1 for s in every
        if s.get("haystack") == "text" and s.get("excluded")
        and "ПУТЬ которого статикой не свернулся" in s["excluded"])

    # ─ вторая дорога и сведение остатка ─
    recall = recall_lines(root)
    every_by_anchor = {(s["file"], s["line"]): s for s in every}
    pop_anchors = {(s["file"], s["line"]) for s in population}
    residue_reasons: Dict[str, int] = {}
    for anchor in recall:
        if anchor in pop_anchors:
            continue
        reason = _residue_reason(every_by_anchor, anchor)
        residue_reasons[reason] = residue_reasons.get(reason, 0) + 1
    unreconciled = residue_reasons.get(
        "сайт разобран, но в население не попал без причины", 0)

    # A обязана быть подмножеством B по «файл + строка»
    recall_set = set(recall)
    outside_recall = sorted(a for a in pop_anchors if a not in recall_set)

    markers_hist: Dict[str, int] = {}
    for site in population:
        for m in site.get("markers", []):
            markers_hist[m] = markers_hist.get(m, 0) + 1

    # ─ признак без замера: скобка не закрыта, а обрыва НЕТ ─
    marker_without_measurement = [
        {"file": s["file"], "line": s["line"], "markers": s.get("markers", []),
         "reason": s["probe"].get("reason")}
        for s in stable if "unclosed_bracket" in s.get("markers", [])
    ]

    findings: List[str] = []
    findings.append(
        f"[НАСЕЛЕНИЕ] утверждений, ищущих литерал-«начало структуры» в ТЕКСТЕ "
        f"исходника соседа: {len(population)}; зовов-утверждений о вхождении "
        f"разобрано всего {len(every)}, из них стог-КОНТЕЙНЕР "
        f"{kinds.get('container', 0)} — это НЕ дефект и в население не входит")
    if not population:
        findings.append(
            "[ТРЕТИЙ ИСХОД] население ПУСТО — класс одиночный: единственный "
            "носитель (приёмка ADR-333) починен, и это замер, а не молчание")
    findings.append(
        f"[ОБРЫВ, ЗАМЕР] доказанный обрыв: {len(truncating)} · устойчиво: "
        f"{len(stable)} · утверждают СУЩЕСТВОВАНИЕ, а не содержимое: "
        f"{len(existence_only)} · не измерено: {len(unmeasured)}. «Не измерено» "
        f"не складывается ни с «устойчиво», ни с нулём")
    if existence_only:
        findings.append(
            f"[НЕ ПРЕДМЕТ ЗАКАЗА] у {len(existence_only)} сайт(ов) литерал "
            f"обрывается ДО первого элемента структуры (`имя_зова(`): это "
            f"утверждение о СУЩЕСТВОВАНИИ, а не частичная претензия о "
            f"содержимом — складывать их с обрывом значило бы уверенно ответить "
            f"не на тот вопрос")
    for site in truncating:
        findings.append(
            f"[CRITICAL] {site['file']}:{site['line']} судит о структуре "
            f"{site['probe'].get('structure')} в {site.get('neighbour')} "
            f"подстрокой её текста; удаление элемента ЗА концом литерала "
            f"вердикт НЕ меняет — утверждение к нему слепо")
    for site in unmeasured:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {site['file']}:{site['line']} — "
            f"{site['probe'].get('reason')}")
    if marker_without_measurement:
        findings.append(
            f"[ПРИЗНАК БЕЗ ЗАМЕРА] у {len(marker_without_measurement)} сайт(ов) "
            f"скобка не закрыта, а обрыва замер НЕ показал — признак не есть "
            f"приговор, и читать метку как вердикт нельзя")
    findings.append(
        f"[ГРАНИЦА ЗАМЕРА] ещё {text_without_neighbour} утверждени(е/я/й) ищут "
        f"такой же литерал в тексте файла, ПУТЬ которого статикой не свернулся "
        f"(временный каталог, фикстура, аргумент). О них замер не утверждает "
        f"НИЧЕГО — ни что они слепы, ни что устойчивы")
    findings.append(
        f"[ПОЛНОТА] дорога B (по форме зова) насчитала {len(recall)} строк; "
        f"остаток B\\A разобран по названным причинам "
        f"({len(residue_reasons)} род(а/ов)), несведённого: {unreconciled}")
    if outside_recall:
        findings.append(
            f"[CRITICAL] {len(outside_recall)} сайт(ов) населения НЕ видны "
            f"полнотной дороге — надмножество нарушено, сверка не состоялась")

    if truncating:
        status = STATUS_CRITICAL
    elif outside_recall or unreconciled:
        status = STATUS_UNMEASURED
    elif unmeasured:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "generated_at": now.isoformat(),
        "status": status,
        "overall": status,
        "counts": {
            "assertion_sites": len(every),
            "population": len(population),
            "truncating": len(truncating),
            "stable": len(stable),
            "existence_only": len(existence_only),
            "unmeasured": len(unmeasured),
            "recall_lines": len(recall),
            "residue_unreconciled": unreconciled,
            "outside_recall": len(outside_recall),
            "text_without_neighbour": text_without_neighbour,
        },
        "population": [
            {"file": s["file"], "line": s["line"], "form": s["form"],
             "markers": s.get("markers", []), "neighbour": s.get("neighbour"),
             "literal": s["literal"], "probe": s["probe"]}
            for s in population
        ],
        "truncation": {
            "truncating": [{"file": s["file"], "line": s["line"],
                            "neighbour": s.get("neighbour"),
                            "structure": s["probe"].get("structure")}
                           for s in truncating],
            "stable": [{"file": s["file"], "line": s["line"],
                        "reason": s["probe"].get("reason")} for s in stable],
            "unmeasured": [{"file": s["file"], "line": s["line"],
                            "reason": s["probe"].get("reason")}
                           for s in unmeasured],
            "existence_only": [{"file": s["file"], "line": s["line"],
                                "literal": s["literal"]} for s in existence_only],
            "marker_without_measurement": marker_without_measurement,
        },
        "haystack_kinds": kinds,
        "excluded_classes": excluded_classes,
        "text_without_neighbour": text_without_neighbour,
        "markers": markers_hist,
        "recall": {
            "lines": len(recall),
            "residue_reasons": residue_reasons,
            "population_outside_recall": outside_recall,
        },
        "findings": findings,
        "advisory": (
            "ADVISORY: прибор только ЧИТАЕТ исходники набора и возмущает копию "
            "текста В ПАМЯТИ. Ни один тест не правится, не скипается и не "
            "сужается (инв. #16); POLLED_ADAPTERS, пины, писатель журнала "
            "решений, TriggerParams, пороги RiskPolicy v1.0, потолки "
            "концентрации, стоп-кран и живой трек НЕ тронуты."),
        "what_it_does_not_prove": (
            "НЕ ДОКЛАДЫВАЕТ: верно ли само утверждение по существу (обрыв — "
            "это про то, чего оно НЕ видит, а не про то, что оно утверждает), "
            "и каким был бы вердикт при другом возмущении той же структуры: "
            "удаляется РОВНО последний элемент за концом литерала."),
    }


def format_report(doc: dict) -> List[str]:
    lines = [f"substring_structure_assertions: {doc.get('overall')}"]
    lines.extend(doc.get("findings") or [])
    return lines


def run(root: Optional[str] = None, *, now=None, write: bool = True,
        data_dir: Optional[str] = None) -> dict:
    """Форма ступени переписей: `root` — КОРЕНЬ ДЕРЕВА (ADR-326)."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    out_dir = Path(data_dir) if data_dir else Path(root) / "data"
    doc = measure(Path(root), now=now)
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(out_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="население утверждений, судящих о структуре по подстроке "
                    "её сериализованного вида (заказ #567)")
    ap.add_argument("--root", default=None, help="КОРЕНЬ ДЕРЕВА")
    ap.add_argument("--data-dir", default=None, help="каталог данных, если не <root>/data")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    root = args.root or str(Path(__file__).resolve().parents[2])
    data_dir = args.data_dir or os.environ.get("SPA_DATA_DIR")
    doc = run(root=root, write=not args.no_write, data_dir=data_dir)
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
