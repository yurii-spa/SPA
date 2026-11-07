#!/usr/bin/env python3
"""spa_core/monitoring/declared_collection_census.py — «заметит ли кто-нибудь, что
объявленный перечень ОПУСТЕЛ?»

# LLM_FORBIDDEN

**Зачем.** Мутационная проба цикла #1058 (ADR-939) применила 14 мутаций и 11 убила.
Из трёх выживших один смотрел прямо в вердикт прибора: ``AGGRAVATING = {"env":
"handbuilt"}`` заменили на ``AGGRAVATING = {}``, и **весь набор остался зелёным**.
Причина — форма ЧТЕНИЯ, а не слабость тестов: единственный читатель перечня перебирал
его циклом (``any(… for axis, outcome in AGGRAVATING.items())``), а пустой перечень
даёт циклу НОЛЬ витков. ``any`` над пустым истинно-ложен молча, ``all`` над пустым
истинен для КАЖДОЙ строки — и в обе стороны это **ЛОЖНОЕ УСИЛЕНИЕ**: прибор печатает
«находок нет» там, где он не посмотрел ни разу.

Этот класс тише красного теста и поэтому опаснее: красное видно, а ноль — нет. Заказ
G929 п. 3 (ADR-939) ставит вопрос дословно: **сколько ещё ОБЪЯВЛЕННЫХ перечней в
``spa_core/`` читаются только циклом ``for … in <перечень>`` без вопроса о
непустоте**; мерить AST, а не грепом, и чинить что-либо ТОЛЬКО ПОСЛЕ замера населения.

**ЧЕТЫРЕ двери, у каждой свой вопрос и свой третий исход (инв. #17).** Склеивать их
нельзя: они чинятся разным, и перечень, опасный по одной оси, безвреден по другой.

====================  ======================================================
дверь                 вопрос, на который она отвечает
====================  ======================================================
``reader_door``       ЧИТАЕТ ли перечень кто-нибудь вообще — «читателя нет»
                      это ДРУГОЙ класс (мёртвое объявление), и слить его с
                      нашим значило бы выдать мёртвый код за ложное усиление
``iter_door``         ПЕРЕБИРАЮТ ли перечень — без итерации пустота вреда
                      этого рода не приносит
``empty_door``        СПРАШИВАЕТ ли ХОТЬ КТО-ТО о непустоте: ``if NAME`` ·
                      ``not NAME`` · ``assert NAME`` · ``len(NAME)`` ·
                      ``bool(NAME)`` · сравнение с пустым литералом · член
                      ``and``/``or``. Это и есть ПРОТИВОЯДИЕ класса — ровно
                      его #1058 и дописал (``assert cec.AGGRAVATING``)
``other_door``        есть ли чтение, ОТЛИЧНОЕ от итерации и от вопроса о
                      непустоте (``x in NAME`` · ``NAME[k]`` · ``NAME.get`` ·
                      передача аргументом). Такое чтение пустоту ОБЫЧНО
                      проявляет иначе — исключением, промахом, отказом, —
                      поэтому предмет оно СНИМАЕТ, а не усугубляет
====================  ======================================================

**ПРОЗРАЧНЫЕ ОБЁРТКИ — не оговорка, а несущая часть замера.** Вред не исчезает от того,
что перечень перед циклом завернули: ``{**A, **AGGRAVATING}.items()`` отдаёт циклу
пустоту ровно так же, как сам ``AGGRAVATING``. Поэтому путь от имени до читателя
прослеживается ЧЕРЕЗ обёртки, сохраняющие пустоту (``.items()``/``.keys()``/
``.values()``, ``list``/``tuple``/``set``/``frozenset``/``sorted``/``reversed``/
``enumerate``/``iter``, распаковка ``{**N}``/``[*N]``, объединение ``A | B`` и
``A + B``) — и это ВЫБОР прибора, печатаемый в отчёте. Остановись он на ``**`` —
единственный ИЗВЕСТНЫЙ предмет класса выпал бы из населения, то есть прибор ответил бы
«пусто» о том, чего не видел (урок ADR-935).

**Чтение привязывается к МОДУЛЮ ОБЪЯВЛЕНИЯ, а не к голому имени (ADR-942, цикл
#1061).** Прежняя редакция ключевала чтения ОДНИМ именем, и этот выбор был назван
вслух как ошибка «в сторону НЕнаходки» — но цена оказалась не оговоркой, а дефектом
того же класса, против которого прибор написан: ``assert ПЕРЕЧЕНЬ``, дописанный для
ОДНОГО модуля, снимал с предмета ВСЕ одноимённые перечни дерева. Замер #1060
(ADR-941): два РАЗНЫХ ``_TS_KEYS`` — ``spa_core/audit/data_integrity.py`` и
``spa_core/monitoring/bounded_window_census.py`` — получили дословно один список из
семи чтений, и ОДНО противоядие сняло с предмета ОБА. Население коллизии: **368**
имён объявлено более чем в одном месте, **1365** объявлений (31,6 % поверхности) в
коллизии. Ошибка шла в сторону ЛОЖНОГО УСИЛЕНИЯ — предмет НЕДОсчитывался.

Привязка читает ИМПОРТЫ файла-читателя (``_imports``) и области связывания имён
(``_scope_bindings``), и у неё ЧЕТЫРЕ исхода (``RESOLUTION_KINDS``):

====================  ======================================================
исход привязки        что он означает
====================  ======================================================
``module``            чтение названо: ``from pkg.mod import NAME`` ·
                      ``import pkg.mod as m`` + ``m.NAME`` · голое ``NAME``
                      при объявлении В ТОМ ЖЕ файле. Зачитывается РОВНО
                      этому объявлению
``local``             имя связано в области функции/класса либо прочитано
                      как ``self.NAME``/``cls.NAME`` — это НЕ объявление
                      уровня модуля, и зачитывать его нельзя никому
                      (дословный случай ``_TS_KEYS`` внутри функций
                      ``daily_operations_report.py``)
``foreign``           имя ввезено из модуля ВНЕ дерева (``typing`` и др.)
``unresolved``        форма не разобрана (звёздный импорт, атрибут
                      выражения, голое имя без импорта). **ТРЕТИЙ ИСХОД:**
                      такое чтение не зачитывается объявлению И не даёт
                      объявлению попасть в предмет — соответствующая ось
                      становится ``unmeasured``
====================  ======================================================

Направление ошибки теперь названо точнее: нераспознанная форма не оправдывает ни
находку, ни её отсутствие (инв. #17). Цена — объявления, у которых одноимённое
чтение не разобрано, уходят в ``not_excluded``, а не в ``subject``.

**Предмет НЕ ЕСТЬ дефект, и это граница утверждения, а не осторожность.** Прибор
доказывает, что ОПУСТЕВШИЙ перечень не будет замечен НИ ОДНИМ его читателем. Вреден ли
этот перечень пустым — зависит от смысла витка цикла (находка? правило? строка
отчёта?), и смысл AST не читает. Поэтому ``subject`` есть ВЕРХНЯЯ граница вреда, а
подтверждённые дефекты считаются ГЛАЗАМИ по поимённому перечню — так же, как в
ADR-939 (предмет 2 из 220, подтверждённых 0).

**Чего прибор НЕ докладывает** (названо, а не умолчано):

* перечни, собираемые В РАНТАЙМЕ (из JSON, из реестра, из ``globals()``): поверхность —
  ЛИТЕРАЛЬНОЕ объявление, и это сказано вслух;
* имена не в ВЕРХНЕМ регистре и объявления не на уровне модуля (атрибут класса,
  локальная переменная) — ``DECLARED_NAME_RE`` и уровень объявлены константами;
* чтения через ``getattr``/``globals()``/``vars()`` — динамику AST не видит;
* ДОСТАТОЧНОСТЬ вопроса о непустоте: прибор видит, что о непустоте спросили, и не
  судит, спросили ли там, где надо (вопрос в тесте соседнего класса считается);
* цепочку обёрток длиной больше объявленной (``WRAPPER_DEPTH``) — найденное есть
  доказанный МИНИМУМ;
* вызывается ли читатель на самом деле: AST отвечает о форме, не об исполнении.

**Прибор только ЧИТАЕТ** — ни одного байта никуда не пишет и ничего не исполняет.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Где ОБЪЯВЛЯЮТ перечни. Заказ G929 п. 3 называет ``spa_core/`` дословно; каталог,
# которого здесь нет, в население не входит, и это цена, а не пробел.
DECLARATION_ROOTS: Tuple[str, ...] = ("spa_core",)

# Где ИЩУТ читателей. Шире объявления намеренно: перечень, объявленный в
# ``spa_core/`` и спрошенный о непустоте из ``scripts/``, предметом НЕ является, а
# прибор, не заглянувший туда, назвал бы его предметом — то есть выдумал находку.
READER_ROOTS: Tuple[str, ...] = ("spa_core", "scripts", "tests", "studio_shell", "research")

# Вложенные деревья того же клона несут КОПИИ тех же файлов.
SKIP_PARTS: Tuple[str, ...] = (
    ".claude", "node_modules", ".git", "site-packages", "__pycache__", ".pytest_cache",
)

#: Объявлением считается имя в ВЕРХНЕМ регистре (ведущее подчёркивание допустимо)
#: на уровне модуля. Форма — ОБЪЯВЛЕНИЕ, с которым сверяется тест.
DECLARED_NAME_RE = r"^_?[A-Z][A-Z0-9_]*$"

#: Обёртки, СОХРАНЯЮЩИЕ пустоту: пустой вход даёт пустой выход.
TRANSPARENT_CALLS: Tuple[str, ...] = (
    "list", "tuple", "set", "frozenset", "dict", "sorted", "reversed", "enumerate", "iter",
)
TRANSPARENT_METHODS: Tuple[str, ...] = ("items", "keys", "values", "copy")

#: Сколько обёрток прибор проходит, прежде чем сдаться. ВЫБОР, а не свойство дерева.
WRAPPER_DEPTH = 6

#: Вызовы, задающие вопрос о НЕПУСТОТЕ напрямую.
EMPTINESS_CALLS: Tuple[str, ...] = ("len", "bool", "any", "all")

# Объявленные исходы каждой двери. Дверь, вернувшая имя вне своего списка, краснит
# сторожа, а не проезжает молча.
READER_OUTCOMES = ("has_reader", "no_reader", "unmeasured")
ITER_OUTCOMES = ("iterated", "never_iterated", "unmeasured")
EMPTY_OUTCOMES = ("asked", "not_asked", "unmeasured")
OTHER_OUTCOMES = ("only_loop", "other_reads", "unmeasured")

#: Опасная сторона каждой оси ПРЕДМЕТА — ОБЪЯВЛЕНИЕ, с которым сверяется тест:
#: иначе «что считается предметом» жило бы только в теле условия и расходилось бы
#: молча (урок ADR-932 о собственном контракте объявления).
SUBJECT_AXES: Dict[str, str] = {
    "reader": "has_reader",
    "iter": "iterated",
    "empty": "not_asked",
    "other": "only_loop",
}

#: Род чтения. Перечень ЗАМКНУТ: чтение, не попавшее ни в один род, есть ``other``.
READ_KINDS = ("loop", "emptiness", "other")

#: Роды чтения, НЕ являющиеся итерацией. ВЫВОДЯТСЯ из замкнутого ``READ_KINDS``, а
#: не перечисляются руками: разойдись перечень с выводом, и утверждение об
#: избыточности осей (ниже) перестало бы быть верным МОЛЧА.
NON_LOOP_KINDS: Tuple[str, ...] = tuple(k for k in READ_KINDS if k != "loop")

#: ОСИ ``empty`` И ``other`` — ДВЕ ПОЛОВИНЫ ОДНОГО ВОПРОСА, А НЕ ДВА ВОПРОСА.
#:
#: Опасная сторона ``empty`` — «чтений рода ``emptiness`` нет»; опасная сторона
#: ``other`` — «чтений рода ``other`` нет». Роды замкнуты и исчерпывают всё, что
#: не итерация (``NON_LOOP_KINDS``), поэтому КОНЪЮНКЦИЯ этих двух осей говорит
#: ровно одно: «чтения есть, и все они — итерация». Отсюда следствие, которое
#: ОБЯЗАНО быть сказано вслух, потому что отчёт сам по себе внушает обратное:
#:
#:    **никакое перекладывание чтения между родами ``emptiness`` и ``other``
#:    предмета изменить НЕ МОЖЕТ.**
#:
#: Цена умолчания ИЗМЕРЕНА (ADR-943, цикл #1062). Строка отчёта «ось empty:
#: asked 296» читается как «296 перечней защищены», и заказ G932 п. 3 на этом
#: основании попросил расширить ``EMPTINESS_CALLS`` методами проверочных
#: библиотек. Замер: население такого расширения **1186** мест, предмет
#: **571 → 571**, «не исключён» **26 → 26**, то есть покупка РОВНО НОЛЬ; а из
#: 1186 мест вопросом о непустоте не являются 1174 (``assertIn`` 573,
#: ``assertEqual`` 471, ``assertNotIn`` 64 …), и объявить их таковыми значило бы
#: снять перечни с предмета, не добавив ни одной защиты — ровно то ложное
#: усиление, против которого написан ADR-941.
#:
#: Утверждение держит ``spa_core/tests/test_read_kind_axis_is_redundant.py``
#: ДВУМЯ КРАЙНОСТЯМИ на сцене, а не рассуждением.
KIND_AXES_ARE_REDUNDANT = (
    "оси empty и other — две половины ОДНОГО вопроса «есть ли чтение, не "
    "являющееся итерацией»; перекладывание чтения между этими родами предмета "
    "не меняет (ADR-943, замер: предмет 571 -> 571 на обеих крайностях)"
)

#: Чем кончается привязка ОДНОГО чтения к объявлению. Перечень ЗАМКНУТ: привязка,
#: вернувшая исход вне него, краснит сторожа, а не проезжает молча.
RESOLUTION_KINDS = ("module", "local", "foreign", "unresolved")

#: Метка модуля ВНЕ дерева. Путь им быть не может — ни один файл так не называется.
FOREIGN_MODULE = "<вне дерева>"

#: Сколько звеньев родительской цепи прибор проходит, выясняя область имени.
SCOPE_DEPTH = 200

#: Узлы, ВВОДЯЩИЕ область имён. Генераторные выражения сюда НЕ входят намеренно:
#: их цели считаются связанными в объемлющей области, и эта ошибка идёт в сторону
#: ``local``, то есть в сторону НЕзачёта чтения — в сторону НАХОДКИ, не умолчания.
SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class Unmeasured(Exception):
    """Поверхность не прочитана. Поднимается с НАЗВАННОЙ причиной."""


def _iter_py_files(root: Path, declared_roots: Sequence[str]) -> List[Path]:
    out: List[Path] = []
    for rel in declared_roots:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            out.append(path)
    return out


def _parse(path: Path) -> Tuple[Optional[ast.Module], Optional[str]]:
    """Разобрать файл. Второе значение — ПРИЧИНА, по которой не вышло."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover - среда
        return None, f"не прочитан: {type(exc).__name__}: {exc}"
    try:
        return ast.parse(text, filename=str(path)), None
    except SyntaxError as exc:
        return None, f"не разбирается: SyntaxError стр. {exc.lineno}: {exc.msg}"


def _is_container_form(node: ast.AST) -> Optional[str]:
    """Форма ОБЪЯВЛЕННОГО перечня, либо None."""
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Set):
        return "set"
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Tuple):
        return "tuple"
    if isinstance(node, (ast.DictComp, ast.SetComp, ast.ListComp)):
        return "comprehension"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in (
        "dict", "set", "frozenset", "list", "tuple",
    ):
        return f"call:{node.func.id}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitOr, ast.Add)):
        left = _is_container_form(node.left)
        right = _is_container_form(node.right)
        # Объединение считается перечнем, если ХОТЯ БЫ одна сторона — перечень:
        # ``_FOUND_BY_STRICTER_DETECTOR | {...}`` именно такой формы.
        if left or right:
            return "union"
    return None


def _is_empty_literal(node: ast.AST) -> bool:
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple)):
        return not (getattr(node, "keys", None) or getattr(node, "elts", None))
    if isinstance(node, ast.Set):
        return not node.elts
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in (
        "dict", "set", "frozenset", "list", "tuple",
    ):
        return not node.args and not node.keywords
    return False


def declarations(
    root: Optional[Path] = None,
    declaration_roots: Sequence[str] = DECLARATION_ROOTS,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Поверхность: объявленные на уровне модуля перечни.

    Возвращает ``(объявления, непрочитанные_файлы)``. Второе — НЕ пустяк: файл, не
    поддавшийся разбору, мог нести объявление, и молчание о нём сделало бы «не
    измерено» неотличимым от «измерено и равно нулю» (инв. #17).
    """
    import re

    root = root or REPO_ROOT
    name_re = re.compile(DECLARED_NAME_RE)
    found: List[Dict[str, Any]] = []
    broken: List[Dict[str, str]] = []
    for path in _iter_py_files(root, declaration_roots):
        tree, reason = _parse(path)
        if tree is None:
            broken.append({"path": str(path.relative_to(root)), "reason": reason or "?"})
            continue
        for node in tree.body:
            targets: List[ast.expr] = []
            value: Optional[ast.expr] = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None:
                continue
            form = _is_container_form(value)
            if form is None:
                continue
            for target in targets:
                if not isinstance(target, ast.Name) or not name_re.match(target.id):
                    continue
                found.append({
                    "name": target.id,
                    "module": str(path.relative_to(root)),
                    "lineno": node.lineno,
                    "form": form,
                    "empty_today": _is_empty_literal(value),
                })
    return found, broken


def _parent_index(tree: ast.Module) -> Dict[int, Tuple[ast.AST, str]]:
    """Связь ребёнок → (родитель, имя поля). Поле нужно: ``iter`` у ``for`` и
    ``test`` у ``if`` — РАЗНЫЕ вопросы, а узел у них один и тот же тип."""
    index: Dict[int, Tuple[ast.AST, str]] = {}
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        index[id(item)] = (parent, field)
            elif isinstance(value, ast.AST):
                index[id(value)] = (parent, field)
    return index


def _climb_transparent(
    node: ast.AST, index: Dict[int, Tuple[ast.AST, str]], depth: int = WRAPPER_DEPTH
) -> ast.AST:
    """Подняться через обёртки, СОХРАНЯЮЩИЕ пустоту, до выражения, которое читают."""
    current = node
    for _ in range(depth):
        parent_field = index.get(id(current))
        if parent_field is None:
            return current
        parent, field = parent_field
        # ``NAME.items()`` / ``NAME.keys()`` → прозрачно
        if isinstance(parent, ast.Attribute) and field == "value" and parent.attr in TRANSPARENT_METHODS:
            call = index.get(id(parent))
            if call is not None and isinstance(call[0], ast.Call) and call[1] == "func":
                current = call[0]
                continue
            current = parent
            continue
        # ``list(NAME)`` / ``sorted(NAME)`` → прозрачно
        if isinstance(parent, ast.Call) and field == "args" and isinstance(parent.func, ast.Name) \
                and parent.func.id in TRANSPARENT_CALLS:
            current = parent
            continue
        # ``{**NAME}`` / ``[*NAME]`` → прозрачно
        if isinstance(parent, ast.Dict) and field == "values":
            current = parent
            continue
        if isinstance(parent, ast.Starred):
            current = parent
            continue
        # ``A | NAME`` / ``A + NAME`` → прозрачно
        if isinstance(parent, ast.BinOp) and isinstance(parent.op, (ast.BitOr, ast.Add)):
            current = parent
            continue
        return current
    return current


def _classify_read(node: ast.AST, index: Dict[int, Tuple[ast.AST, str]]) -> str:
    """Род ОДНОГО чтения: ``loop`` · ``emptiness`` · ``other``."""
    effective = _climb_transparent(node, index)
    parent_field = index.get(id(effective))
    if parent_field is None:
        return "other"
    parent, field = parent_field

    if isinstance(parent, (ast.For, ast.AsyncFor)) and field == "iter":
        return "loop"
    if isinstance(parent, ast.comprehension) and field == "iter":
        return "loop"

    if isinstance(parent, ast.Call) and field == "args" and isinstance(parent.func, ast.Name) \
            and parent.func.id in EMPTINESS_CALLS:
        return "emptiness"
    if isinstance(parent, (ast.If, ast.While, ast.IfExp)) and field == "test":
        return "emptiness"
    if isinstance(parent, ast.Assert) and field == "test":
        return "emptiness"
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        return "emptiness"
    if isinstance(parent, ast.BoolOp):
        return "emptiness"
    if isinstance(parent, ast.Compare):
        others = [parent.left, *parent.comparators]
        if any(o is not effective and _is_empty_literal(o) for o in others):
            return "emptiness"
        return "other"
    return "other"


def _dotted_name(node: ast.AST) -> Optional[str]:
    """``a.b.c`` из цепочки ``Attribute``/``Name``, либо None, если в основании
    цепочки не имя (вызов, индекс, литерал)."""
    parts: List[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _module_rel(root: Path, dotted: str) -> Optional[str]:
    """Точечное имя модуля → путь ВНУТРИ дерева, либо None (модуль не наш).

    Пакет считается модулем по ``__init__.py``: ``from spa_core import monitoring``
    есть ввоз модуля, а не имени, и спутать их значило бы привязать чтение к
    несуществующему объявлению.
    """
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return None
    candidate = root.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return str(candidate.relative_to(root))
    package = root.joinpath(*parts) / "__init__.py"
    if package.is_file():
        return str(package.relative_to(root))
    return None


def _imports(tree: ast.Module, root: Path, rel: str) -> Dict[str, Any]:
    """Карта импортов файла-ЧИТАТЕЛЯ.

    ``modules`` — алиас или точечное имя → путь модуля (или ``FOREIGN_MODULE``);
    ``names``   — имя В ЭТОМ файле → (путь модуля, имя в ОБЪЯВЛЕНИИ);
    ``star``    — есть ли ``from X import *`` (источник голого имени не назван).
    """
    modules: Dict[str, str] = {}
    names: Dict[str, Tuple[str, str]] = {}
    star = False
    package = rel.rsplit("/", 1)[0] if "/" in rel else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _module_rel(root, alias.name) or FOREIGN_MODULE
                modules[alias.asname or alias.name] = target
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split("/") if package else []
                up = node.level - 1
                base_parts = base_parts[: len(base_parts) - up] if up else base_parts
                prefix = ".".join([p for p in base_parts if p])
                dotted = f"{prefix}.{node.module}" if node.module else prefix
            else:
                dotted = node.module or ""
            owner = _module_rel(root, dotted) or FOREIGN_MODULE
            for alias in node.names:
                if alias.name == "*":
                    star = True
                    continue
                as_module = _module_rel(root, f"{dotted}.{alias.name}") if dotted else None
                if as_module is not None:
                    modules[alias.asname or alias.name] = as_module
                else:
                    names[alias.asname or alias.name] = (owner, alias.name)
    return {"modules": modules, "names": names, "star": star}


def _walk_own_scope(nodes: Sequence[ast.AST]):
    """Узлы СВОЕЙ области: в тело вложенной области прибор не спускается —
    связанное там имя снаружи не видно."""
    stack: List[ast.AST] = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, SCOPE_TYPES):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _bound_in(scope: ast.AST) -> set:
    """Имена, СВЯЗАННЫЕ в этой области. ``global``/``nonlocal`` вычитаются: такое
    имя принадлежит уровню модуля, и считать его локальным значило бы потерять
    настоящее чтение объявления."""
    bound: set = set()
    declared_outer: set = set()
    if isinstance(scope, ast.Module):
        body: List[ast.AST] = list(scope.body)
    elif isinstance(scope, ast.Lambda):
        body = [scope.body]
    else:
        body = list(getattr(scope, "body", []))
    args = getattr(scope, "args", None)
    if isinstance(args, ast.arguments):
        for arg in [*getattr(args, "posonlyargs", []), *args.args, *args.kwonlyargs]:
            bound.add(arg.arg)
        if args.vararg:
            bound.add(args.vararg.arg)
        if args.kwarg:
            bound.add(args.kwarg.arg)
    for node in _walk_own_scope(body):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            declared_outer.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound - declared_outer


def _scope_bindings(tree: ast.Module) -> Tuple[set, Dict[int, set]]:
    """(имена уровня МОДУЛЯ, id области → связанные в ней имена)."""
    per_scope: Dict[int, set] = {}
    for node in ast.walk(tree):
        if isinstance(node, SCOPE_TYPES):
            per_scope[id(node)] = _bound_in(node)
    return _bound_in(tree), per_scope


def _enclosing_scopes(
    node: ast.AST, index: Dict[int, Tuple[ast.AST, str]], depth: int = SCOPE_DEPTH
) -> List[ast.AST]:
    """Области, объемлющие узел, от внутренней к внешней (модуль не включён)."""
    out: List[ast.AST] = []
    current: ast.AST = node
    for _ in range(depth):
        parent_field = index.get(id(current))
        if parent_field is None:
            break
        parent = parent_field[0]
        if isinstance(parent, SCOPE_TYPES):
            out.append(parent)
        current = parent
    return out


def _resolve_read(
    node: ast.AST, index: Dict[int, Tuple[ast.AST, str]], ctx: Dict[str, Any]
) -> Tuple[str, Optional[str], Optional[str], str]:
    """Привязать ОДНО чтение к модулю объявления.

    Возвращает ``(исход, модуль, имя_в_объявлении, причина)``; исход — член
    ``RESOLUTION_KINDS``, и у ``unresolved`` причина ОБЯЗАТЕЛЬНА.
    """
    if isinstance(node, ast.Attribute):
        dotted = _dotted_name(node.value)
        if dotted is None:
            return "unresolved", None, None, "атрибут выражения, а не модуля"
        head = dotted.split(".")[0]
        if head in ("self", "cls"):
            return "local", None, None, "атрибут экземпляра/класса — не уровень модуля"
        target = ctx["modules"].get(dotted)
        if target is None and "." in dotted:
            base = ctx["modules"].get(head)
            if base and base != FOREIGN_MODULE and base.endswith("/__init__.py"):
                prefix = base[: -len("/__init__.py")].replace("/", ".")
                target = _module_rel(ctx["root"], f"{prefix}.{dotted.split('.', 1)[1]}")
        if target == FOREIGN_MODULE:
            return "foreign", None, None, "модуль вне дерева"
        if target is not None:
            return "module", target, node.attr, ""
        return "unresolved", None, None, f"основание «{dotted}» не объявлено импортом"

    name = node.id  # type: ignore[attr-defined]
    for scope in _enclosing_scopes(node, index):
        if name in ctx["scope_bound"].get(id(scope), ()):
            return "local", None, None, "связано в области функции/класса"
    if name in ctx["names"]:
        module, declared = ctx["names"][name]
        if module == FOREIGN_MODULE:
            return "foreign", None, None, "ввезено из модуля вне дерева"
        return "module", module, declared, ""
    if name in ctx["modules"]:
        return "local", None, None, "имя модуля, а не перечня"
    if name in ctx["module_bound"]:
        return "module", ctx["rel"], name, ""
    if ctx["star"]:
        return "unresolved", None, None, "звёздный импорт — источник имени не назван"
    return "unresolved", None, None, "голое имя без импорта и без связывания в файле"


def reads(
    root: Optional[Path] = None,
    reader_roots: Sequence[str] = READER_ROOTS,
) -> Tuple[
    Dict[Tuple[str, str], Dict[str, List[str]]],
    Dict[str, Dict[str, List[str]]],
    List[Dict[str, str]],
    Dict[str, int],
]:
    """Все чтения всех ВЕРХНЕРЕГИСТРОВЫХ имён, привязанные к МОДУЛЮ объявления.

    Возвращает ``(привязанные, неразобранные, непрочитанные_файлы, счёт_исходов)``:

    * ``привязанные``   — ``(модуль, имя) → род → места``. Ключ ПАРНЫЙ, и это
      несущая часть замера: одноимённые перечни разных модулей больше не делят
      чтения, а противоядие снимает с предмета РОВНО свой перечень (ADR-942).
    * ``неразобранные`` — ``имя → род → места`` для чтений, чью форму прибор не
      разобрал. Такое чтение МОГЛО быть о любом одноимённом объявлении, поэтому
      оно запирает соответствующую ось в ``unmeasured`` (инв. #17), а не
      зачитывается и не игнорируется.
    * ``счёт_исходов``  — сколько чтений пришлось на каждый член
      ``RESOLUTION_KINDS``. Печатается отчётом: охват прибора называет он сам.

    Один проход по дереву: иначе замер был бы O(имён × файлов) и не укладывался
    бы в такт.
    """
    import re

    root = root or REPO_ROOT
    name_re = re.compile(DECLARED_NAME_RE)
    bound: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
    unbound: Dict[str, Dict[str, List[str]]] = {}
    broken: List[Dict[str, str]] = []
    counts: Dict[str, int] = {kind: 0 for kind in RESOLUTION_KINDS}
    for path in _iter_py_files(root, reader_roots):
        tree, reason = _parse(path)
        if tree is None:
            broken.append({"path": str(path.relative_to(root)), "reason": reason or "?"})
            continue
        index = _parent_index(tree)
        rel = str(path.relative_to(root))
        module_bound, scope_bound = _scope_bindings(tree)
        ctx: Dict[str, Any] = {
            "root": root, "rel": rel,
            "module_bound": module_bound, "scope_bound": scope_bound,
            **_imports(tree, root, rel),
        }
        for node in ast.walk(tree):
            name: Optional[str] = None
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                name = node.id
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                name = node.attr
            if name is None or not name_re.match(name):
                continue
            kind = _classify_read(node, index)
            outcome, module, declared, _reason = _resolve_read(node, index, ctx)
            counts[outcome] = counts.get(outcome, 0) + 1
            place = f"{rel}:{node.lineno}"
            if outcome == "module" and module is not None and declared is not None:
                bucket = bound.setdefault((module, declared), {k: [] for k in READ_KINDS})
                bucket[kind].append(place)
            elif outcome == "unresolved":
                bucket = unbound.setdefault(name, {k: [] for k in READ_KINDS})
                bucket[kind].append(place)
    return bound, unbound, broken, counts


def census(
    root: Optional[Path] = None,
    declaration_roots: Sequence[str] = DECLARATION_ROOTS,
    reader_roots: Sequence[str] = READER_ROOTS,
) -> Dict[str, Any]:
    """Замер класса. Три исхода различимы, и «не измерено» нулём не считается."""
    root = root or REPO_ROOT
    decls, broken_decl = declarations(root, declaration_roots)
    bound_reads, unbound_reads, broken_read, resolution = reads(root, reader_roots)
    # Файл, не поддавшийся разбору, мог нести ЛЮБОЕ чтение ⇒ обе двери о чтении
    # становятся `unmeasured` у ВСЕХ объявлений. Это fail-CLOSED, а не придирка:
    # пропущенный `assert NAME` превратил бы «противоядие есть» в «предмета нет».
    reads_unmeasured = bool(broken_read)

    rows: List[Dict[str, Any]] = []
    for decl in decls:
        buckets = bound_reads.get((decl["module"], decl["name"]), {k: [] for k in READ_KINDS})
        # Объявление само себя не читает: строка объявления из чтений вычитается.
        own = f"{decl['module']}:{decl['lineno']}"
        places = {k: [p for p in v if p != own] for k, v in buckets.items()}
        total = sum(len(v) for v in places.values())
        # Чтения ТОГО ЖЕ имени, чью форму прибор не разобрал. Зачесть их значило бы
        # вернуть слияние по имени (ADR-942); промолчать — выдумать находку. Поэтому
        # они запирают РОВНО ту ось, о которой могли бы ответить (инв. #17).
        murky = {
            k: [p for p in v if p != own]
            for k, v in unbound_reads.get(decl["name"], {k: [] for k in READ_KINDS}).items()
        }
        murky_total = sum(len(v) for v in murky.values())
        if reads_unmeasured:
            axes = {k: "unmeasured" for k in ("reader", "iter", "empty", "other")}
        else:
            axes = {
                "reader": "has_reader" if total else (
                    "unmeasured" if murky_total else "no_reader"),
                "iter": "iterated" if places["loop"] else (
                    "unmeasured" if murky["loop"] else "never_iterated"),
                "empty": "asked" if places["emptiness"] else (
                    "unmeasured" if murky["emptiness"] else "not_asked"),
                "other": "other_reads" if places["other"] else (
                    "unmeasured" if murky["other"] else "only_loop"),
            }
        dangerous = [axis for axis, want in SUBJECT_AXES.items() if axes[axis] == want]
        unmeasured_axes = [a for a, v in axes.items() if v == "unmeasured"]
        subject = len(dangerous) == len(SUBJECT_AXES)
        not_excluded = (
            not subject
            and bool(unmeasured_axes)
            and all(axes[a] == want for a, want in SUBJECT_AXES.items() if a not in unmeasured_axes)
        )
        rows.append({
            **decl,
            "axes": axes,
            "reads": places,
            "read_count": total,
            "unresolved_reads": murky,
            "unresolved_read_count": murky_total,
            "subject": subject,
            "not_excluded": not_excluded,
        })

    subject_rows = [r for r in rows if r["subject"]]
    return {
        "root": str(root),
        "declaration_roots": list(declaration_roots),
        "reader_roots": list(reader_roots),
        "wrapper_depth": WRAPPER_DEPTH,
        "surface": len(rows),
        "subject": len(subject_rows),
        "not_excluded": sum(1 for r in rows if r["not_excluded"]),
        "empty_today": sum(1 for r in rows if r["empty_today"]),
        "subject_and_empty_today": sum(1 for r in subject_rows if r["empty_today"]),
        "by_axis": {
            axis: {
                outcome: sum(1 for r in rows if r["axes"][axis] == outcome)
                for outcome in outcomes
            }
            for axis, outcomes in (
                ("reader", READER_OUTCOMES), ("iter", ITER_OUTCOMES),
                ("empty", EMPTY_OUTCOMES), ("other", OTHER_OUTCOMES),
            )
        },
        "resolution": resolution,
        "colliding_names": sum(
            1 for name, count in _name_counts(decls).items() if count > 1),
        "declarations_in_collision": sum(
            count for count in _name_counts(decls).values() if count > 1),
        "unparsable_declaration_files": broken_decl,
        "unparsable_reader_files": broken_read,
        "unmeasured": bool(broken_decl or broken_read),
        "rows": rows,
    }


def _name_counts(decls: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Сколько РАЗНЫХ объявлений носит каждое имя. Число коллизии печатается: пока
    прибор сливал чтения по имени, именно оно было ценой замера (ADR-942)."""
    counts: Dict[str, int] = {}
    for decl in decls:
        counts[decl["name"]] = counts.get(decl["name"], 0) + 1
    return counts


def report(result: Dict[str, Any], limit: int = 40) -> str:
    """Отчёт для человека. ОХВАТ прибора печатается им самим (урок ADR-935)."""
    lines: List[str] = []
    lines.append(
        f"перепись объявленных перечней: поверхность {result['surface']}, "
        f"корни объявления {', '.join(result['declaration_roots'])}, "
        f"корни читателей {', '.join(result['reader_roots'])}, "
        f"глубина обёрток {result['wrapper_depth']}"
    )
    lines.append(
        "   привязка чтений к МОДУЛЮ объявления: "
        + " · ".join(f"{k} {result['resolution'].get(k, 0)}" for k in RESOLUTION_KINDS)
        + f"; имён в коллизии {result['colliding_names']}"
        f" (объявлений {result['declarations_in_collision']})"
    )
    for axis in ("reader", "iter", "empty", "other"):
        pairs = " · ".join(f"{k} {v}" for k, v in result["by_axis"][axis].items())
        lines.append(f"   ось {axis}: {pairs}")
    lines.append(f"   ⚠️ {KIND_AXES_ARE_REDUNDANT}")
    lines.append(
        f"   ПРЕДМЕТ (все четыре оси на опасной стороне): {result['subject']} · "
        f"НЕ ИСКЛЮЧЁН: {result['not_excluded']} · "
        f"пуст УЖЕ СЕГОДНЯ: {result['empty_today']} "
        f"(из них предмет: {result['subject_and_empty_today']})"
    )
    if result["unmeasured"]:
        lines.append("   ⚠️ НЕ ИЗМЕРЕНО — файлы не разобраны:")
        for item in (result["unparsable_declaration_files"] + result["unparsable_reader_files"])[:10]:
            lines.append(f"      {item['path']} — {item['reason']}")
    shown = [r for r in result["rows"] if r["subject"]][:limit]
    for row in shown:
        loops = ", ".join(row["reads"]["loop"][:3]) or "—"
        lines.append(
            f"   ▫️ {row['name']} ({row['form']}, {row['module']}:{row['lineno']}"
            f"{', ПУСТ СЕГОДНЯ' if row['empty_today'] else ''}) — "
            f"чтений {row['read_count']}, все итерацией: {loops}"
        )
    return "\n".join(lines)
