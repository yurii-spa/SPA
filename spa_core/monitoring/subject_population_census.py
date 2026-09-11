"""Сколько сторожей выводят своё НАСЕЛЕНИЕ из ТЕКСТА соседа — и сколько из них слепы.

Заказ #565 (стоячая карточка CIO) поставлен дословно так:

> Сколько ЕЩЁ сторожей выводят своё население ОДНОЙ формой — и у скольких из них
> эта форма опирается на СОГЛАШЕНИЕ ОБ ИМЕНИ, а не на структуру? Первым
> результатом обязано быть НАСЕЛЕНИЕ: сколько проверок в наборе строят список
> субъектов регулярным выражением по исходнику соседа, и у скольких в выражении
> участвует имя переменной, имя функции или префикс — то есть то, что завтрашний
> автор волен назвать иначе, НЕ сломав предмет проверки. Ноль таких ⇒ третий
> исход «класс одиночный», закрытый замером.
>
> Ловушка названа заранее. Соблазн — грепать ``re.compile`` в тестах. Это ответ
> на другой вопрос: форма бывает и списком литералов, и ``glob``, и обходом
> каталога, и у неё не одна запись. И отдельно: «проверка строит население
> регуляркой» НЕ равно «проверка слепа» — слеп тот, у кого в выражении стои́т
> переименовываемое; сказать это надо прежде, чем называть долю.

## Что случилось у ADR-327 и почему вопрос не праздный

Храповик ADR-326 выводил население ступени переписей формой
``_\\w+ = X.run(root=args.root)``. Ведущее подчёркивание у ПРИЁМНИКА записи —
свойство того, как автор назвал четыре свои переменные (``_ulc``, ``_lps``,
``_sms``, ``_drri``), а не свойство зова: соседние сорок зовутся дословно так же
и пишут в ``rrep``, ``trep``, ``crep``, ``afd``. Под храповиком было **12 из
42**, и порог «не меньше десяти» при этом был ЗЕЛЁНЫМ: нижняя граница истинна и
на подмножестве, о собственной слепоте сказать не может.

Вопрос заказа — про КЛАСС: сколько ещё таких сторожей.

## Два числа, и второе НЕ выводится из первого

``население`` — сколько проверок строят список субъектов из текста соседа.
``слепые`` — у скольких из них список СЖИМАЕТСЯ от переименования, которое
предмет проверки не трогает. Первое не есть обвинение: форма зова, форма
импорта, имя параметра — это КОНТРАКТ, и сторож, краснеющий на их изменение,
краснеет ВЕРНО.

## Слепота меряется ПОВЕДЕНЧЕСКИ, а не по виду выражения

Статический признак («в шаблоне стои́т приклеенный к маске литерал») — это
ПРИЗНАК, и у признака нет права быть ответом: ровно на подмене признака
ответом погорел ADR-326. Поэтому слепота здесь — ЗАМЕР:

1. взять исходник субъекта и посчитать население ``findall``;
2. переименовать в нём КАЖДУЮ локальную привязку (цель присваивания, цель
   ``for``, ``with … as``) в свежее имя ``zzN`` — переименование локального
   имени поведение не меняет ПО ПОСТРОЕНИЮ, ни один чужой файл его не видит;
3. посчитать население ещё раз. **Сжалось ⇒ сторож слеп**, и это доказано,
   а не заподозрено.

Импорт-псевдонимы, имена ``def``/``class``, имена параметров и ключевых
аргументов НЕ трогаются намеренно: их переименование ВИДНО снаружи, то есть
меняет предмет проверки, и сжатие населения от него было бы верным красным.

## Полнота населения — ОТДЕЛЬНОЕ утверждение, доказанное ВТОРОЙ дорогой

Урок ADR-327 буквально: счётчик, выведенный одной формой, о своей слепоте
сказать не может. Поэтому население выводится дважды и НЕЗАВИСИМО:

``A`` (точная)   разбор AST: чтение исходника соседа → пометка значения →
                 многоместное извлечение (``findall``/``finditer``) над ним.
``B`` (полнотная) чистый текстовый обход по ФОРМЕ ЗОВА ``.findall(`` /
                 ``.finditer(`` в файле, который вообще читает исходник репо.
                 Про пометку значений не знает ничего.

``B`` обязана быть НАДМНОЖЕСТВОМ. Каждый остаток ``B \\ A`` получает НАЗВАННУЮ
причину (стог — не исходник соседа, шаблон добыт в рантайме, …); остаток без
причины — ТРЕТИЙ ИСХОД ``unmeasured``, и он не складывается с нулём. Сузится
дорога ``A`` — сверка покраснеет, а не промолчит.

## Ловушка заказа выполнена буквально: прочие формы считаются ПОРОЗНЬ

Список литералов, ``glob`` по префиксу имени и обход каталога — тоже способы
получить население, но вопрос о слепоте у них РАЗНЫЙ (у обхода каталога имени
в выражении нет вовсе, он слеп быть не может ПО ПОСТРОЕНИЮ). Сводить их в одно
число значило бы дать верный ответ не на тот вопрос, поэтому они названы и
посчитаны отдельно, и в долю слепых не входят.

ADVISORY. Прибор читает исходники и НАЗЫВАЕТ население. Ничего не чинит и
капитал не двигает: ``POLLED_ADAPTERS``, пины, писатель журнала решений, пороги
RiskPolicy v1.0, потолки концентрации, стоп-кран и живой трек не трогаются.
Замер не читает ``data/`` вовсе — вопрос о КОДЕ.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

OUTPUT_FILENAME = "subject_population_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Каталоги проверок — ровно те пять, что гейтит CI (строка команды в CLAUDE.md).
#: Выбор назван вслух: «набор» заказа это то, на чём стои́т зелёный CI, а не все
#: `.py` репозитория.
_CHECK_DIRS = (
    "tests",
    "spa_core/tests",
    "scripts/tests",
    "spa_core/analytics/gross_of",
    "research/cards",
)

#: Чтение ИСХОДНИКА (не артефакта): эти зовы дают текст файла.
_SOURCE_READS = ("read_text", "getsource", "read")

#: Расширения, которые считаются ИСХОДНИКОМ соседа. `.json` сюда не входит
#: намеренно: артефакт — это данные, а вопрос заказа о ТЕКСТЕ кода.
_SOURCE_SUFFIXES = (".py", ".sh", ".yml", ".yaml", ".plist", ".md", ".toml", ".cfg")

#: Многоместное извлечение: даёт КОЛЛЕКЦИЮ, то есть население.
_MULTI_EXTRACT = ("findall", "finditer")

_NEW_NAME = "zz{}"


# ─────────────────────────── общее ───────────────────────────

#: Разбор одного и того же файла повторяется десятки раз (обход зовущих у
#: каждого сайта-помощника). Ключ включает отметку и размер: файл, изменившийся
#: под прибором, обязан разбираться заново, иначе замер начнёт отвечать про
#: вчерашнее дерево. Деревья НЕ мутируются ни одним потребителем — переписчик
#: населения разбирает свою копию.
_PARSE_CACHE: Dict[Tuple[str, int, int], Optional[ast.Module]] = {}
_TEXT_CACHE: Dict[Tuple[str, int, int], str] = {}


def _stat_key(path: Path) -> Optional[Tuple[str, int, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def _text(path: Path) -> Optional[str]:
    key = _stat_key(path)
    if key is None:
        return None
    if key not in _TEXT_CACHE:
        try:
            _TEXT_CACHE[key] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return _TEXT_CACHE[key]


def _parse(path: Path) -> Optional[ast.Module]:
    key = _stat_key(path)
    if key is None:
        return None
    if key in _PARSE_CACHE:
        return _PARSE_CACHE[key]
    text = _text(path)
    try:
        tree = ast.parse(text) if text is not None else None
    except (SyntaxError, UnicodeDecodeError, ValueError):
        tree = None
    _PARSE_CACHE[key] = tree
    return tree


def check_files(root: Path) -> List[Path]:
    out: List[Path] = []
    for d in _CHECK_DIRS:
        p = root / d
        if p.is_dir():
            out.extend(sorted(p.rglob("*.py")))
    return out


def _rel(root: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(p)


# ─────────────────── дорога A: разбор AST ────────────────────

def _is_source_read(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _SOURCE_READS)


def taint_source_names(tree: ast.Module) -> Set[str]:
    """Имена, чьё значение происходит от чтения исходника.

    Пометка идёт ПО ИМЕНИ в пределах модуля и до неподвижной точки — так же,
    как её вёл `_injected_clock` (ADR, цикл #477). Область видимости при этом
    НЕ различается, и это сказано вслух: имя параметра, совпавшее с помеченной
    локальной переменной, будет помечено тоже. Для полноты (дорога A обязана
    быть подмножеством B) такая огрублённость безопасна, для точности — нет,
    поэтому каждый сайт дороги A ещё и сверяется дорогой B.
    """
    tainted: Set[str] = set()

    def derives(node: ast.AST) -> bool:
        if _is_source_read(node):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return derives(node.func.value)
        if isinstance(node, ast.Name):
            return node.id in tainted
        if isinstance(node, ast.Subscript):
            return derives(node.value)
        return False

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            targets: List[ast.AST] = []
            value: Optional[ast.AST] = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.NamedExpr):
                targets, value = [node.target], node.value
            elif isinstance(node, ast.For):
                targets, value = [node.target], node.iter
            if value is None or not derives(value):
                continue
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id not in tainted:
                    tainted.add(tgt.id)
                    changed = True
    return tainted


_TAINT_CACHE: Dict[int, Set[str]] = {}


def taint_of(tree: ast.Module) -> Set[str]:
    """Кэш пометки: неподвижная точка считается по одному дереву десятки раз."""
    key = id(tree)
    if key not in _TAINT_CACHE:
        _TAINT_CACHE[key] = taint_source_names(tree)
    return _TAINT_CACHE[key]


def module_patterns(tree: ast.Module) -> Dict[str, str]:
    """Модульные `re.compile("…")` → текст шаблона."""
    out: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "compile"
                and isinstance(fn.value, ast.Name) and fn.value.id == "re"):
            continue
        args = node.value.args
        if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = args[0].value
    return out


def path_folder(check_file: Path, root: Path, known: Dict[str, Path]):
    """Свёртка выражения-пути в абсолютный путь. Возвращает функцию.

    Свёртываются ровно те формы, что встречаются в наборе:
    ``Path(__file__)``, ``…resolve()``, ``…parents[N]`` и цепочка ``… / "имя"``.
    Не свернулось — ``None``, и субъект сайта станет `unmeasured` с названной
    причиной, а не угаданным путём.
    """

    def fold(node: ast.AST) -> Optional[Path]:
        if isinstance(node, ast.Name):
            return known.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = fold(node.left)
            if left is None:
                return None
            if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
                return left / node.right.value
            return None
        if isinstance(node, ast.Subscript):
            base = node.value
            if isinstance(base, ast.Attribute) and base.attr == "parents":
                anchor = fold(base.value)
                idx = node.slice
                if anchor is not None and isinstance(idx, ast.Constant) \
                        and isinstance(idx.value, int):
                    parents = anchor.resolve().parents
                    if idx.value < len(parents):
                        return parents[idx.value]
            return None
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in ("resolve", "absolute"):
                return fold(fn.value)
            if isinstance(fn, ast.Name) and fn.id == "Path" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Name) and a.id == "__file__":
                    return check_file
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    q = Path(a.value)
                    return q if q.is_absolute() else (root / a.value)
            return None
        return None

    return fold


def module_paths(tree: ast.Module, check_file: Path, root: Path) -> Dict[str, Path]:
    """Модульные константы-пути → абсолютный путь.

    Сворачиваются ровно две формы, обе встречаются в наборе:
    ``Path(__file__).resolve().parents[N]`` и цепочка ``… / "имя"``.
    Не свернулось — константы просто нет в словаре, и субъект сайта станет
    `unmeasured` с названной причиной, а не угаданным путём.
    """
    out: Dict[str, Path] = {}
    fold = path_folder(check_file, root, out)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        folded = fold(node.value)
        if folded is None:
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                out[tgt.id] = folded
    return out


def _haystack_path(node: ast.AST, fold, read_of: Dict[str, ast.AST],
                   seen: Optional[Set[int]] = None) -> Optional[Path]:
    """Из выражения-стога вытащить путь читаемого файла, если он статичен."""
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return None
    seen.add(id(node))
    if isinstance(node, ast.Name):
        src = read_of.get(node.id)
        return _haystack_path(src, fold, read_of, seen) if src is not None else None
    if _is_source_read(node):
        assert isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        return fold(node.func.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _haystack_path(node.func.value, fold, read_of, seen)
    return None


def _haystack_paths_from_loop(node: ast.AST, tree: ast.Module, fold,
                              read_of: Dict[str, ast.AST]) -> Optional[List[Path]]:
    """Стог — переменная цикла по ``glob``/``rglob``: субъектов МНОЖЕСТВО.

    Единичным путём их не назвать, но замерить можно каждого: сжатие населения
    хотя бы у одного и есть слепота. Ноль найденных файлов ⇒ ``None``, то есть
    «не измерено», а не «чисто».
    """
    name = None
    if isinstance(node, ast.Name):
        origin = read_of.get(node.id)
        if origin is not None and _is_source_read(origin):
            assert isinstance(origin, ast.Call) and isinstance(origin.func, ast.Attribute)
            recv = origin.func.value
            if isinstance(recv, ast.Name):
                name = recv.id
    if name is None:
        return None
    for n in ast.walk(tree):
        if not (isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                and n.target.id == name):
            continue
        it = n.iter
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) \
                and it.func.attr in ("glob", "rglob") and it.args:
            base = fold(it.func.value)
            arg0 = it.args[0]
            if base is None or not (isinstance(arg0, ast.Constant)
                                    and isinstance(arg0.value, str)):
                return None
            found = sorted(base.rglob(arg0.value) if it.func.attr == "rglob"
                           else base.glob(arg0.value))
            return [q for q in found if q.is_file()] or None
    return None


def _param_of(node: ast.AST, site: ast.AST, parents: Dict[int, ast.AST]
              ) -> Optional[Tuple[str, int, str]]:
    """Стог — параметр ОХВАТЫВАЮЩЕЙ функции? (имя функции, номер, имя параметра).

    Искать «любую функцию с таким параметром» нельзя: имя `src` в одном файле
    носят параметры трёх разных помощников, и первый попавшийся назвал бы
    ЧУЖИХ зовущих — верный ответ не на тот вопрос.
    """
    if not isinstance(node, ast.Name):
        return None
    fn = _enclosing_scope(site, parents)
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    a = fn.args
    args = [x.arg for x in list(a.posonlyargs) + list(a.args)]
    if node.id in args:
        return fn.name, args.index(node.id), node.id
    return None


def resolve_param_subjects(root: Path, fn_name: str, pos: int,
                           param: str) -> Tuple[List[Path], List[str]]:
    """Субъекты помощника называет ЗОВУЩИЙ — значит, идти надо к нему.

    «Стог — параметр функции» это НЕ «измерить нельзя»: это «спрашивать надо
    не здесь». Обход зовущих даёт настоящее население субъектов; зовущий, чей
    аргумент не свёрнут, попадает в НАЗВАННЫЙ остаток, а не в ноль.
    """
    subjects: List[Path] = []
    unresolved: List[str] = []
    for f in check_files(root):
        tree = _parse(f)
        if tree is None:
            continue
        src = _text(f) or ""
        if fn_name not in src:
            continue
        paths = module_paths(tree, f, root)
        fold = path_folder(f, root, paths)
        module_origin = _read_origins(tree)
        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = (callee.id if isinstance(callee, ast.Name)
                    else callee.attr if isinstance(callee, ast.Attribute) else None)
            if name != fn_name:
                continue
            arg: Optional[ast.AST] = None
            if len(node.args) > pos:
                arg = node.args[pos]
            else:
                for kw in node.keywords:
                    if kw.arg == param:
                        arg = kw.value
            if arg is None:
                unresolved.append(f"{_rel(root, f)}:{node.lineno} — аргумент не передан позиционно и не назван")
                continue
            local = _scoped_origins(node, parents, module_origin)
            one = _haystack_path(arg, fold, local)
            if one is not None:
                subjects.append(one)
                continue
            many = _haystack_paths_from_loop(arg, tree, fold, local)
            if many:
                subjects.extend(many)
                continue
            unresolved.append(f"{_rel(root, f)}:{node.lineno} — аргумент зовущего не свёрнут в путь")
    uniq: List[Path] = []
    seen: Set[str] = set()
    for q in subjects:
        key = str(q)
        if key not in seen:
            seen.add(key)
            uniq.append(q)
    return uniq, unresolved


def _haystack_kind(node: ast.AST, tree: ast.Module) -> str:
    """Чем стог является, когда путь не свернулся. Причина обязана быть НАЗВАНА."""
    if isinstance(node, ast.Name):
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            a = fn.args
            args = [x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)]
            if node.id in args:
                return ("стог — ПАРАМЕТР функции "
                        f"`{fn.name}({node.id})`: ни один зовущий не назвал субъект путём")
        for n in ast.walk(tree):
            if isinstance(n, ast.For) and isinstance(n.target, ast.Name) \
                    and n.target.id == node.id:
                return "стог — переменная ЦИКЛА: субъектов много, единичным путём их не назвать"
    return "путь стога не свёрнут в константу — субъект назвать нечем"


def _read_origins(tree: ast.Module) -> Dict[str, ast.AST]:
    """Имя → выражение, из которого оно получило свой текст (последнее присваивание).

    Модульная область. Для сайтов внутри функции берётся `_scoped_origins`:
    имя `src` встречается в одном файле по пять раз, и «последнее присваивание
    во всём модуле» назвало бы ЧУЖОЙ субъект — верный ответ не на тот вопрос.
    """
    out: Dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
    return out


def _enclosing_scope(node: ast.AST, parents: Dict[int, ast.AST]) -> Optional[ast.AST]:
    cur: Optional[ast.AST] = node
    while cur is not None and not isinstance(
            cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
        cur = parents.get(id(cur))
    return cur


def _scoped_origins(site: ast.AST, parents: Dict[int, ast.AST],
                    module_level: Dict[str, ast.AST]) -> Dict[str, ast.AST]:
    """Присваивания, видимые ИМЕННО этому сайту: своя функция поверх модуля."""
    out = dict(module_level)
    scope = _enclosing_scope(site, parents)
    if scope is None or isinstance(scope, ast.Module):
        return out
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, node.iter)
    return out


def _parent_map(tree: ast.Module) -> Dict[int, ast.AST]:
    out: Dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


#: Роль извлечения. Два РАЗНЫХ предмета, и мерить их одним числом нельзя.
#: ``coverage``    — коллекция ЕСТЬ список субъектов, о котором дальше судят.
#: ``prohibition`` — коллекция обязана быть ПУСТОЙ (запрет), населения нет.
ROLE_COVERAGE = "coverage"
ROLE_PROHIBITION = "prohibition"


def _extraction_role(call: ast.Call, parents: Dict[int, ast.AST]) -> str:
    """Запрет опознаётся по сравнению с пустотой у ближайших предков."""
    node: Optional[ast.AST] = call
    for _ in range(4):
        parent = parents.get(id(node)) if node is not None else None
        if parent is None:
            break
        if isinstance(parent, ast.Compare):
            for other in [parent.left] + list(parent.comparators):
                if isinstance(other, (ast.List, ast.Tuple, ast.Set)) and not other.elts:
                    return ROLE_PROHIBITION
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            return ROLE_PROHIBITION
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute):
            meth = parent.func.attr
            if meth in ("assertFalse", "assertNotIn"):
                return ROLE_PROHIBITION
            if meth in ("assertEqual", "assertListEqual", "assertCountEqual"):
                for a in parent.args:
                    if isinstance(a, (ast.List, ast.Tuple, ast.Set)) and not a.elts:
                        return ROLE_PROHIBITION
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) \
                and parent.func.id == "len":
            node = parent
            continue
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 \
                and isinstance(parent.targets[0], ast.Name):
            return _role_of_bound_name(parent.targets[0].id, parents, parent)
        node = parent
    return ROLE_COVERAGE


def _role_of_bound_name(name: str, parents: Dict[int, ast.AST],
                        assign: ast.Assign) -> str:
    """Извлечение положили в переменную — роль решает то, что с НЕЙ делают.

    Замер этого цикла: `forbidden = re.findall(...)` и строкой ниже
    `assert forbidden == []`. Ближайшие предки зова о запрете не знают ничего,
    и роль вышла бы `coverage` — верный ответ не на тот вопрос.
    """
    scope: Optional[ast.AST] = assign
    while scope is not None and not isinstance(
            scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
        scope = parents.get(id(scope))
    if scope is None:
        return ROLE_COVERAGE
    for node in ast.walk(scope):
        if isinstance(node, ast.Compare):
            parts = [node.left] + list(node.comparators)
            has_name = any(isinstance(x, ast.Name) and x.id == name for x in parts)
            has_empty = any(isinstance(x, (ast.List, ast.Tuple, ast.Set)) and not x.elts
                            for x in parts)
            if has_name and has_empty:
                return ROLE_PROHIBITION
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) \
                and isinstance(node.operand, ast.Name) and node.operand.id == name:
            return ROLE_PROHIBITION
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("assertEqual", "assertFalse", "assertListEqual",
                                       "assertCountEqual"):
            args = list(node.args)
            if any(isinstance(x, ast.Name) and x.id == name for x in args) and (
                    node.func.attr == "assertFalse"
                    or any(isinstance(x, (ast.List, ast.Tuple, ast.Set)) and not x.elts
                           for x in args)):
                return ROLE_PROHIBITION
    return ROLE_COVERAGE


def forward_sites(root: Path) -> Tuple[List[dict], List[dict]]:
    """Дорога A. Возвращает (сайты, не-измеренные)."""
    sites: List[dict] = []
    unmeasured: List[dict] = []
    for f in check_files(root):
        tree = _parse(f)
        if tree is None:
            unmeasured.append({"file": _rel(root, f), "reason": "файл не разобран (синтаксис/кодировка)"})
            continue
        tainted = taint_of(tree)
        pats = module_patterns(tree)
        paths = module_paths(tree, f, root)
        fold = path_folder(f, root, paths)
        origins = _read_origins(tree)
        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in _MULTI_EXTRACT:
                continue
            recv = node.func.value
            pattern: Optional[str]
            hay: Optional[ast.AST]
            if isinstance(recv, ast.Name) and recv.id == "re":
                arg0 = node.args[0] if node.args else None
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    pattern = arg0.value
                elif isinstance(arg0, ast.Name) and arg0.id in pats:
                    pattern = pats[arg0.id]
                else:
                    pattern = None
                hay = node.args[1] if len(node.args) > 1 else None
            elif isinstance(recv, ast.Name) and recv.id in pats:
                pattern = pats[recv.id]
                hay = node.args[0] if node.args else None
            else:
                continue
            if hay is None or not _is_source_text(hay, tainted):
                continue
            local = _scoped_origins(node, parents, origins)
            subject = _haystack_path(hay, fold, local)
            subject_set: Optional[List[Path]] = None
            via_caller: Optional[Tuple[str, int, str]] = None
            caller_unresolved: List[str] = []
            if subject is None:
                subject_set = _haystack_paths_from_loop(hay, tree, fold, local)
            if subject is None and not subject_set:
                via_caller = _param_of(hay, node, parents)
                if via_caller is not None:
                    found, caller_unresolved = resolve_param_subjects(
                        root, via_caller[0], via_caller[1], via_caller[2])
                    subject_set = found or None
            site = {
                "file": _rel(root, f),
                "line": node.lineno,
                "pattern": pattern,
                "subject": _rel(root, subject) if subject else None,
                "subject_set": [_rel(root, q) for q in subject_set] if subject_set else None,
                "subject_via_caller": via_caller[0] if via_caller else None,
                "caller_unresolved": caller_unresolved or None,
                "role": _extraction_role(node, parents),
            }
            if pattern is None:
                site["pattern_unmeasured"] = (
                    "шаблон собран в рантайме — статике не даётся ПО ПОСТРОЕНИЮ")
            if subject is None and subject_set is None:
                site["subject_unmeasured"] = _haystack_kind(hay, tree)
            sites.append(site)
    return sites, unmeasured


def _is_source_text(node: ast.AST, tainted: Set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in tainted
    if _is_source_read(node):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _is_source_text(node.func.value, tainted)
    return False


# ────────────── дорога B: полнотная, по ФОРМЕ ЗОВА ───────────

_CALL_FORM = re.compile(r"\.(findall|finditer)\s*\(")


def call_form_sites(root: Path) -> List[dict]:
    """Дорога B. Про пометку значений не знает ничего — только форма зова.

    Отбор файлов: тот, что вообще читает ИСХОДНИК репозитория (в тексте есть
    зов чтения и упоминание расширения исходника). Файл, не читающий ничего,
    стогом соседа располагать не может.
    """
    out: List[dict] = []
    for f in check_files(root):
        src = _text(f)
        if src is None:
            continue
        reads = any(f".{r}(" in src or f".{r}()" in src for r in _SOURCE_READS)
        mentions_source = any(s in src for s in _SOURCE_SUFFIXES)
        if not (reads and mentions_source):
            continue
        for i, line in enumerate(src.splitlines(), start=1):
            m = _CALL_FORM.search(line)
            if m:
                out.append({"file": _rel(root, f), "line": i, "form": m.group(1),
                            "text": line.strip()[:160]})
    return out


# ─────────────── слепота: поведенческий замер ────────────────

def local_binding_names(tree: ast.Module) -> Set[str]:
    """Имена, привязываемые ВНУТРИ тел функций, — и только они.

    Переименование такого имени НЕ видно ни одному чужому файлу, поэтому оно
    законно: предмет проверки от него не меняется. Всё, что видно снаружи
    (модульные константы, импорт-псевдонимы, имена ``def``/``class``, параметры,
    ключевые аргументы, атрибуты), не трогается — их переименование меняет
    контракт, и сжатие населения от него было бы ВЕРНЫМ красным.
    """
    names: Set[str] = set()
    escaping: Set[str] = set()

    # привязанное на уровне МОДУЛЯ видно снаружи — из класса локальных вон
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name):
                        escaping.add(sub.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    escaping.add(sub.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            escaping.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                escaping.add(al.asname or al.name.split(".")[0])

    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            escaping.update(node.names)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                escaping.add(al.asname or al.name.split(".")[0])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            escaping.add(node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)):
                escaping.add(arg.arg)
            if a.vararg:
                escaping.add(a.vararg.arg)
            if a.kwarg:
                escaping.add(a.kwarg.arg)

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            targets: List[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                targets = [node.target]
            elif isinstance(node, ast.For):
                targets = [node.target]
            elif isinstance(node, ast.With):
                targets = [it.optional_vars for it in node.items if it.optional_vars]
            for tgt in targets:
                if tgt is None:
                    continue
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
    return names - escaping


def rename_local_bindings_tree(tree: ast.Module) -> Tuple[ast.Module, int]:
    """Переименовать каждую локальную привязку в свежее ``zzN`` — В САМОМ ДЕРЕВЕ.

    Правка идёт по AST, а не по смещениям в тексте: смещения внутри f-строк
    зависят от версии интерпретатора, и правка по ним однажды уже съела
    закрывающую кавычку (замер этого цикла). Вердикт, зависящий от версии
    Python, — та же бомба, что литеральная дата: он отвечает про ХОСТ, а не
    про код.

    Новое имя намеренно не сохраняет НИЧЕГО от старого — ни префикса, ни
    подчёркивания, ни длины: соглашение об имени и есть измеряемое.
    """
    targets = local_binding_names(tree)
    if not targets:
        return tree, 0
    mapping = {name: _NEW_NAME.format(i) for i, name in enumerate(sorted(targets), start=1)}
    renamed = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in mapping:
            node.id = mapping[node.id]
            renamed += 1
    return tree, renamed


def _fstring_spans(tree: ast.Module) -> List[Tuple[int, int, int, int]]:
    """Границы всех f-строк. Внутрь них правка по смещениям не лезет.

    Смещения подвыражений внутри f-строки зависят от версии интерпретатора:
    до 3.12 они указывают на начало всей строки, и правка по ним съедает
    закрывающую кавычку (замерено этим циклом на `findings_bridge`). Вердикт,
    зависящий от версии Python, — та же бомба, что литеральная дата.
    """
    spans: List[Tuple[int, int, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and node.end_lineno is not None:
            spans.append((node.lineno, node.col_offset,
                          node.end_lineno, node.end_col_offset))
    return spans


def _inside(spans, lineno: int, col: int) -> bool:
    for l0, c0, l1, c1 in spans:
        if (lineno, col) >= (l0, c0) and (lineno, col) < (l1, c1):
            return True
    return False


def rename_local_bindings(src: str) -> Tuple[Optional[str], int, bool]:
    """Переименовать локальные привязки, СОХРАНИВ раскладку исходника.

    Возвращает (текст, сколько имён тронуто, была ли пропущена f-строка).
    Нормализация через ``ast.unparse`` здесь не годится: она меняет кавычки и
    отступы, а шаблоны набора в них упираются — на `pat_rotation` население
    падало 1 → 0 от ОДНОЙ нормализации, и «устойчиво» было бы замером кавычек,
    а не слепоты.
    """
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None, 0, False
    targets = local_binding_names(tree)
    if not targets:
        return src, 0, False
    mapping = {name: _NEW_NAME.format(i) for i, name in enumerate(sorted(targets), start=1)}
    spans = _fstring_spans(tree)
    edits: Dict[int, List[Tuple[int, int, str]]] = {}
    renamed = 0
    skipped_fstring = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id in mapping):
            continue
        if node.end_lineno != node.lineno:
            skipped_fstring = True
            continue
        if _inside(spans, node.lineno, node.col_offset):
            skipped_fstring = True
            continue
        edits.setdefault(node.lineno, []).append(
            (node.col_offset, node.end_col_offset, mapping[node.id]))
        renamed += 1
    # ВАЖНО: `col_offset` у `ast` — смещение в БАЙТАХ utf-8, а не в символах.
    # На строке с кириллицей символьная нарезка сдвигает правку и съедает
    # соседнее слово (замерено этим циклом: `else` в тернарном выражении).
    blines = src.encode("utf-8").splitlines(keepends=True)
    for lineno, reps in edits.items():
        if lineno - 1 >= len(blines):
            continue
        bline = blines[lineno - 1]
        for start, end, new in sorted(reps, key=lambda r: -r[0]):
            bline = bline[:start] + new.encode("utf-8") + bline[end:]
        blines[lineno - 1] = bline
    out = b"".join(blines).decode("utf-8")
    try:
        ast.parse(out)
    except (SyntaxError, ValueError):
        return None, renamed, skipped_fstring
    return out, renamed, skipped_fstring


def rename_probe(pattern: str, subject_src: str) -> dict:
    """Сжалось ли население от законного переименования локальных имён.

    Раскладка субъекта сохраняется, поэтому «до» и «после» отличаются РОВНО
    переименованием. Если хоть одно совпадение шаблона попало внутрь f-строки,
    которую правка не трогала, вердикт не выносится: это ровно та щель, через
    которую «устойчиво» стало бы fail-OPEN.
    """
    try:
        rx = re.compile(pattern, re.M | re.S) if _needs_flags(pattern) else re.compile(pattern)
    except re.error as exc:
        return {"verdict": "unmeasured", "reason": f"шаблон не компилируется: {exc}"}
    before = len(rx.findall(subject_src))
    if before == 0:
        return {"verdict": "unmeasured", "before": 0,
                "reason": "население субъекта пусто — сжиматься нечему"}
    renamed_src, n_renamed, skipped_fstring = rename_local_bindings(subject_src)
    if renamed_src is None:
        return {"verdict": "unmeasured", "before": before,
                "reason": "субъект не переписан (разбор или пересборка не удались)"}
    if n_renamed == 0:
        return {"verdict": "unmeasured", "before": before, "renamed": 0,
                "reason": "в субъекте нет ни одной локальной привязки — возмущать нечего"}
    after = len(rx.findall(renamed_src))
    if after == before and skipped_fstring:
        try:
            spans = _fstring_spans(ast.parse(subject_src))
        except (SyntaxError, ValueError):
            spans = []
        for m in rx.finditer(subject_src):
            head = subject_src[:m.start()]
            line = head.count("\n") + 1
            col = len(head[head.rfind("\n") + 1:].encode("utf-8"))
            if _inside(spans, line, col):
                return {"verdict": "unmeasured", "before": before, "after": after,
                        "renamed": n_renamed,
                        "reason": ("совпадение шаблона лежит внутри f-строки, которую "
                                   "правка не трогала — «устойчиво» здесь было бы "
                                   "fail-OPEN")}
    return {"verdict": "blind" if after < before else "stable",
            "before": before, "after": after, "renamed": n_renamed}


def _needs_flags(pattern: str) -> bool:
    """Шаблоны с якорями строки почти всегда зовутся с `re.M`; без флага замер
    дал бы ноль и объявил бы «нечего сжимать». Флаг ставится ОБА раза — и до,
    и после возмущения, — поэтому сравнение честное."""
    return "^" in pattern or "$" in pattern


#: Статический ПРИЗНАК (не ответ): переименовываемое в шаблоне.
_MARKER_BINDING = re.compile(r"(\\w[+*]|\[[^\]]+\][+*])\s*(\\s\*)?=(?!=)")
_MARKER_PREFIX = re.compile(r"(?<![\\\w])([A-Za-z_][A-Za-z0-9_]*)\\w[+*]")
#: Шаблон прибит к РАСКЛАДКЕ (якорь строки + литеральные пробелы). Это тот же
#: класс, что соглашение об имени, но по другой оси: завтрашний автор волен
#: изменить отступ, НЕ тронув предмет проверки.
_MARKER_INDENT = re.compile(r"\^ {2,}")


def static_markers(pattern: str) -> List[str]:
    marks: List[str] = []
    if _MARKER_BINDING.search(pattern):
        marks.append("constrains-assignment-target")
    m = _MARKER_PREFIX.search(pattern)
    if m:
        marks.append(f"name-prefix:{m.group(1)}")
    if _MARKER_INDENT.search(pattern):
        marks.append("pins-literal-indentation")
    return marks


# ───────────── прочие формы населения: ПОРОЗНЬ ──────────────

_GLOB_NAME = re.compile(r"r?g?lob\(\s*[\"']([^\"']+)[\"']")


def other_form_counts(root: Path) -> Dict[str, int]:
    """Литеральный список · glob по префиксу имени · обход каталога · построчный скан.

    Считаются ОТДЕЛЬНО и в долю слепых не входят: вопрос о слепоте у каждой из
    них свой, а у обхода каталога имени в выражении нет вовсе.
    """
    counts = {"literal_list": 0, "glob_name": 0, "dir_walk": 0, "line_scan": 0}
    for f in check_files(root):
        tree = _parse(f)
        if tree is None:
            continue
        tainted = taint_of(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("glob", "rglob") and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    stem = a.value.split("/")[-1]
                    if stem.startswith("*") or stem == "*":
                        counts["dir_walk"] += 1
                    else:
                        counts["glob_name"] += 1
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "splitlines" \
                    and _is_source_text(node.func.value, tainted):
                counts["line_scan"] += 1
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                elts = node.value.elts
                if len(elts) >= 3 and all(
                        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts):
                    names = [e.value for e in elts]
                    if all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./-]*", n) for n in names):
                        counts["literal_list"] += 1
    return counts


# ───────────────────────── замер ─────────────────────────────

def measure(root: Path, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    root = Path(root).resolve()

    sites, parse_unmeasured = forward_sites(root)
    b_sites = call_form_sites(root)

    a_keys = {(s["file"], s["line"]) for s in sites}
    b_keys = {(s["file"], s["line"]) for s in b_sites}

    #: A обязана быть подмножеством B. Не подмножество — сузилась дорога B.
    a_not_in_b = sorted(f"{f}:{l}" for f, l in (a_keys - b_keys))

    residue_named: List[dict] = []
    residue_unmeasured: List[dict] = []
    for s in b_sites:
        if (s["file"], s["line"]) in a_keys:
            continue
        reason = _residue_reason(root, s)
        (residue_named if reason else residue_unmeasured).append(
            {**s, "reason": reason} if reason else s)

    # слепота — поведенчески, и ТОЛЬКО у роли `coverage`
    blind: List[dict] = []
    stable: List[dict] = []
    blind_unmeasured: List[dict] = []
    prohibition = [s for s in sites if s["role"] == ROLE_PROHIBITION]
    coverage = [s for s in sites if s["role"] == ROLE_COVERAGE]
    for s in coverage:
        if not s.get("pattern"):
            blind_unmeasured.append({**s, "probe_reason": s.get("pattern_unmeasured")})
            continue
        subjects: List[Path] = []
        if s.get("subject"):
            subjects = [root / s["subject"]]
        elif s.get("subject_set"):
            subjects = [root / q for q in s["subject_set"]]
        if not subjects:
            blind_unmeasured.append({**s, "probe_reason": s.get("subject_unmeasured")})
            continue
        pys = [q for q in subjects if q.is_file() and q.suffix == ".py"]
        if not pys:
            suffixes = sorted({q.suffix or "без расширения" for q in subjects})
            blind_unmeasured.append({
                **s, "probe_reason":
                    f"субъект(ы) не python ({', '.join(suffixes)}) — законное "
                    "переименование локальной привязки для них не определено"})
            continue
        probes = [rename_probe(s["pattern"], q.read_text(encoding="utf-8", errors="replace"))
                  for q in pys]
        shrank = [pr for pr in probes if pr["verdict"] == "blind"]
        stable_pr = [pr for pr in probes if pr["verdict"] == "stable"]
        agg = {
            "subjects_probed": len(pys),
            "shrank": len(shrank),
            "stable": len(stable_pr),
            "unmeasured": len(probes) - len(shrank) - len(stable_pr),
            "before": sum(pr.get("before", 0) for pr in probes),
            "after": sum(pr.get("after", 0) for pr in probes),
        }
        rec = {**s, "probe": agg, "static_markers": static_markers(s["pattern"])}
        if shrank:
            agg["verdict"] = "blind"
            blind.append(rec)
        elif stable_pr:
            agg["verdict"] = "stable"
            stable.append(rec)
        else:
            agg["verdict"] = "unmeasured"
            blind_unmeasured.append({
                **rec, "probe_reason": probes[0].get("reason") if probes else "зонд не выполнен"})

    # признак против замера: расхождение — находка о ПРИЗНАКЕ, не о коде
    marker_only = [s["file"] + ":" + str(s["line"]) for s in stable if s["static_markers"]]
    probe_only = [s["file"] + ":" + str(s["line"])
                  for s in blind if not s["static_markers"]]

    others = other_form_counts(root)

    findings: List[str] = []
    critical = warn = unchecked = 0

    findings.append(
        f"НАСЕЛЕНИЕ (первым результатом, как требует заказ): зовов, извлекающих "
        f"КОЛЛЕКЦИЮ регулярным выражением по исходнику соседа — **{len(sites)}** "
        f"(дорога A, разбор AST) при {len(b_sites)} зовах формы "
        f"`.findall(`/`.finditer(` в дороге B")
    findings.append(
        f"РОЛЬ решает предмет и считается ПОРОЗНЬ: список субъектов (coverage) "
        f"— {len(coverage)}; запрет, где коллекция обязана быть ПУСТОЙ "
        f"(prohibition) — {len(prohibition)}. Слепота спрашивается только у "
        f"coverage: у запрета населения нет по построению")

    if len(coverage) == 0:
        findings.append(
            "ТРЕТИЙ ИСХОД «класс одиночный»: кроме сторожа ADR-327 таких проверок "
            "нет — и это ЗАМЕР, а не молчание")
    else:
        findings.append(
            f"«строит население регуляркой» ≠ «слеп»: из {len(coverage)} сайтов "
            f"поведенчески СЛЕПЫ {len(blind)}, устойчивы {len(stable)}, "
            f"не измерено {len(blind_unmeasured)}")

    for s in blind:
        critical += 1
        p = s["probe"]
        findings.append(
            f"СЛЕП {s['file']}:{s['line']} — население субъекта {s['subject']} "
            f"сжимается {p['before']} → {p['after']} от переименования локальных "
            f"привязок, которого предмет проверки не замечает")

    if a_not_in_b:
        critical += 1
        findings.append(
            "ДОРОГА B СУЗИЛАСЬ: точная дорога A нашла сайты вне полнотной — "
            + ", ".join(a_not_in_b[:10]))

    if residue_unmeasured:
        unchecked += len(residue_unmeasured)
        findings.append(
            f"НЕ ИЗМЕРЕНО: {len(residue_unmeasured)} зов(ов) дороги B без названной "
            "причины остатка — это НЕ ноль и с нулём не складывается")

    if blind_unmeasured:
        unchecked += len(blind_unmeasured)
        findings.append(
            f"НЕ ИЗМЕРЕНО: {len(blind_unmeasured)} сайт(ов) не прошли поведенческий "
            "зонд (шаблон в рантайме · субъект не свёрнут · субъект не python)")

    if parse_unmeasured:
        unchecked += len(parse_unmeasured)
        findings.append(
            f"НЕ ИЗМЕРЕНО: {len(parse_unmeasured)} файл(ов) проверок не разобраны")

    layout_pinned = [f"{s['file']}:{s['line']}" for s in blind_unmeasured
                     if s.get("pattern") and "pins-literal-indentation" in static_markers(s["pattern"])]
    if layout_pinned:
        warn += 1
        findings.append(
            "ПО ДРУГОЙ ОСИ, назван и НЕ измерен: шаблон прибит к литеральному "
            f"отступу у {len(layout_pinned)} сайт(ов) — " + ", ".join(layout_pinned)
            + ". Это тот же класс, что соглашение об имени, но возмутить раскладку "
              "законно этот прибор не умеет (субъект не python, парсера в stdlib "
              "нет) — поэтому ПРИЗНАК, а не приговор")

    if marker_only:
        warn += 1
        findings.append(
            f"ПРИЗНАК БЕЗ ЗАМЕРА: {len(marker_only)} сайт(ов) несут статическую "
            "метку переименовываемого, но население от переименования НЕ сжимается "
            "— метка есть признак, а не приговор")
    if probe_only:
        warn += 1
        findings.append(
            f"ЗАМЕР БЕЗ ПРИЗНАКА: {len(probe_only)} слепых сайт(ов) статическая "
            "метка не назвала — ровно поэтому слепота меряется поведением")

    findings.append(
        "ПОРОЗНЬ (ловушка заказа): прочие способы получить население — "
        f"список литералов {others['literal_list']}, glob по имени "
        f"{others['glob_name']}, обход каталога {others['dir_walk']} "
        f"(слеп быть не может ПО ПОСТРОЕНИЮ: имени в выражении нет), "
        f"построчный скан {others['line_scan']}; в долю слепых НЕ входят")

    if critical:
        status = STATUS_CRITICAL
    elif unchecked:
        status = STATUS_WARNING
    elif warn:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "generated_at": now.isoformat(),
        "status": status,
        "overall": status,
        "counts": {"critical": critical, "warn": warn, "unchecked": unchecked},
        "population": {
            "regex_multi": len(sites),
            "by_call_form": len(b_sites),
            "a_not_in_b": a_not_in_b,
            "residue_named": len(residue_named),
            "residue_unmeasured": len(residue_unmeasured),
        },
        "blindness": {
            "blind": blind,
            "stable": [{"file": s["file"], "line": s["line"],
                        "subject": s["subject"], "probe": s["probe"],
                        "static_markers": s["static_markers"]} for s in stable],
            "unmeasured": blind_unmeasured,
            "marker_without_probe": marker_only,
            "probe_without_marker": probe_only,
        },
        "other_forms": others,
        "sites": sites,
        "residue": residue_named[:50],
        "findings": findings,
        "advisory": (
            "ADVISORY: прибор читает ИСХОДНИКИ проверок и НАЗЫВАЕТ население. "
            "POLLED_ADAPTERS, пины, писатель журнала решений, пороги RiskPolicy "
            "v1.0, потолки концентрации, стоп-кран и живой трек НЕ трогаются; "
            "`data/` замер не читает вовсе"),
    }


def _residue_reason(root: Path, site: dict) -> Optional[str]:
    """Почему зов дороги B не стал сайтом дороги A. Причина обязана быть НАЗВАНА."""
    f = root / site["file"]
    tree = _parse(f)
    if tree is None:
        return None
    tainted = taint_source_names(tree)
    pats = module_patterns(tree)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.lineno != site["line"] or node.func.attr not in _MULTI_EXTRACT:
            continue
        recv = node.func.value
        if isinstance(recv, ast.Name) and recv.id == "re":
            hay = node.args[1] if len(node.args) > 1 else None
        elif isinstance(recv, ast.Name) and recv.id in pats:
            hay = node.args[0] if node.args else None
        elif isinstance(recv, ast.Name):
            return "шаблон не модульный `re.compile` — приёмник зова не разрешён статикой"
        else:
            return "приёмник зова — выражение, а не имя: шаблон статике не даётся"
        if hay is None:
            return "у зова нет аргумента-стога"
        if not _is_source_text(hay, tainted):
            return "стог НЕ происходит от чтения исходника соседа (литерал, артефакт, вывод команды)"
        return None
    return "строка не несёт зова `findall`/`finditer` на уровне AST (комментарий, строка, перенос)"


def format_report(doc: dict) -> List[str]:
    lines = [f"subject_population_census: {doc.get('overall')}"]
    lines.extend(doc.get("findings") or [])
    return lines


def run(root: Optional[str] = None, *, now=None, write: bool = True,
        data_dir: Optional[str] = None) -> dict:
    """Форма ступени переписей: `root` — КОРЕНЬ ДЕРЕВА (ADR-326).

    Явный каталог данных передаётся СВОИМ именем `data_dir=`.
    """
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
        description="население сторожей, выводящих субъектов из текста соседа (заказ #565)")
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
