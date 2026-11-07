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

**Имя сверяется ПО ИМЕНИ, а не по разрешённому импорту.** Чтение ``NAME`` в соседнем
модуле зачтётся даже если это ДРУГОЙ ``NAME``. Ошибка этого выбора идёт в сторону
БОЛЬШЕГО числа чтений, то есть в сторону НЕнаходки: прибор скорее промолчит о предмете,
чем выдумает его. Направление названо, потому что обратное было бы недопустимо.

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


def reads(
    root: Optional[Path] = None,
    reader_roots: Sequence[str] = READER_ROOTS,
) -> Tuple[Dict[str, Dict[str, List[str]]], List[Dict[str, str]]]:
    """Все чтения всех ВЕРХНЕРЕГИСТРОВЫХ имён, разложенные по роду.

    Один проход по дереву: имя → род → места. Иначе замер был бы O(имён × файлов) и
    не укладывался бы в такт.
    """
    import re

    root = root or REPO_ROOT
    name_re = re.compile(DECLARED_NAME_RE)
    out: Dict[str, Dict[str, List[str]]] = {}
    broken: List[Dict[str, str]] = []
    for path in _iter_py_files(root, reader_roots):
        tree, reason = _parse(path)
        if tree is None:
            broken.append({"path": str(path.relative_to(root)), "reason": reason or "?"})
            continue
        index = _parent_index(tree)
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            name: Optional[str] = None
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                name = node.id
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                name = node.attr
            if name is None or not name_re.match(name):
                continue
            kind = _classify_read(node, index)
            bucket = out.setdefault(name, {k: [] for k in READ_KINDS})
            bucket[kind].append(f"{rel}:{node.lineno}")
    return out, broken


def census(
    root: Optional[Path] = None,
    declaration_roots: Sequence[str] = DECLARATION_ROOTS,
    reader_roots: Sequence[str] = READER_ROOTS,
) -> Dict[str, Any]:
    """Замер класса. Три исхода различимы, и «не измерено» нулём не считается."""
    root = root or REPO_ROOT
    decls, broken_decl = declarations(root, declaration_roots)
    read_map, broken_read = reads(root, reader_roots)
    # Файл, не поддавшийся разбору, мог нести ЛЮБОЕ чтение ⇒ обе двери о чтении
    # становятся `unmeasured` у ВСЕХ объявлений. Это fail-CLOSED, а не придирка:
    # пропущенный `assert NAME` превратил бы «противоядие есть» в «предмета нет».
    reads_unmeasured = bool(broken_read)

    rows: List[Dict[str, Any]] = []
    for decl in decls:
        buckets = read_map.get(decl["name"], {k: [] for k in READ_KINDS})
        # Объявление само себя не читает: строка объявления из чтений вычитается.
        own = f"{decl['module']}:{decl['lineno']}"
        places = {k: [p for p in v if p != own] for k, v in buckets.items()}
        total = sum(len(v) for v in places.values())
        if reads_unmeasured:
            axes = {k: "unmeasured" for k in ("reader", "iter", "empty", "other")}
        else:
            axes = {
                "reader": "has_reader" if total else "no_reader",
                "iter": "iterated" if places["loop"] else "never_iterated",
                "empty": "asked" if places["emptiness"] else "not_asked",
                "other": "other_reads" if places["other"] else "only_loop",
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
        "unparsable_declaration_files": broken_decl,
        "unparsable_reader_files": broken_read,
        "unmeasured": bool(broken_decl or broken_read),
        "rows": rows,
    }


def report(result: Dict[str, Any], limit: int = 40) -> str:
    """Отчёт для человека. ОХВАТ прибора печатается им самим (урок ADR-935)."""
    lines: List[str] = []
    lines.append(
        f"перепись объявленных перечней: поверхность {result['surface']}, "
        f"корни объявления {', '.join(result['declaration_roots'])}, "
        f"корни читателей {', '.join(result['reader_roots'])}, "
        f"глубина обёрток {result['wrapper_depth']}"
    )
    for axis in ("reader", "iter", "empty", "other"):
        pairs = " · ".join(f"{k} {v}" for k, v in result["by_axis"][axis].items())
        lines.append(f"   ось {axis}: {pairs}")
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
