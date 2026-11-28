#!/usr/bin/env python3
"""Перепись: у скольких мер класса ADR-1127 есть ОБЪЯВЛЕНИЕ, которое ПЕРЕСОБИРАЕТ прибор.

Направление 1 карточки `inbox-naselenie-mer-bez-voprosa-pri-dostavke-2`
(заказ G1102 п. 2 приказа владельца «Portfolio CIO»):

    «**Общая дверь вместо 264 отдельных.** Один вопрос в момент доставки —
    „уезжает ли набор-зависимая мера, чьё объявление ты не пересобрал“ —
    вместо гейта на каждую меру. Померить: сколько из 264 мер вообще имеют
    ОБЪЯВЛЕНИЕ на диске, которое можно пересобрать прибором (у ADR-1112 его
    нет вовсе — базу ведут руками).»

ЧТО ЭТОТ ПРИБОР ОТВЕЧАЕТ, А ЧТО НЕТ
─────────────────────────────────────────────────────────────────────────────
Он отвечает на вопрос ВОЗМОЖНОСТИ общей двери, а не строит её. Общая дверь
доставки может спросить «ты пересобрал объявление?» только у той меры, чьё
объявление ВООБЩЕ ПЕРЕСОБИРАЕМО: есть файл на диске и есть инструмент, который
этот файл ПИШЕТ. Мера, у которой такого инструмента нет, общей дверью не
закрывается ни одной строкой — её объявление ведут руками (ADR-1112), либо
ожидание живёт в исходнике самой меры и объявления на диске нет вовсе.

Поэтому ответ прибора — РАСПРЕДЕЛЕНИЕ предмета класса по пересобираемости, и
число `producer_writes` среди `subject` есть ВЕРХНЯЯ граница охвата общей
двери, причём завышенная: засчитан любой спрошенный инструмент, который пишет
хоть какой-то путь дерева, а объявлением ЭТОЙ меры он быть не обязан.
Завышение ИЗМЕРЕНО, а не предположено, и свидетель его — известный член
ADR-729: `card_acceptance.py` пишет `architecture/manifest.json` и
`landing/src/data/site_numbers.json`, и ни один из двух объявлением сторожа
потери разделов карточки не является.

ЗАМЕР 28.11 (дерево `origin/main` f11092f4f), предмет 263:

    producer_writes    49   верхняя (завышенная) граница охвата общей двери
    writes_unresolved 121   НЕ ИЗМЕРЕНО — инструмент пишет, цель не сложилась
    no_write_at_all    45   спрошенный инструмент не пишет на диск вовсе
    no_producer        48   инструмента мера не спрашивает ни одного

То есть общая дверь накрывает НЕ БОЛЬШЕ 18,6 % предмета, а 93 меры (35,4 %)
она не накрывает ТОЧНО. Направление 1 карточки как способ ЗАКРЫТЬ класс этим
замером ОПРОВЕРГНУТО: одной дверью вместо 263 гейтов класс не закрывается.
Вилка охвата 49 … 170, и 121 неизмеренных нулём не считаются.

ПОЧЕМУ ЗДЕСЬ СВОЙ СКЛАДЫВАТЕЛЬ ПУТЕЙ, А НЕ `_PathResolver` ПРИБОРА ADR-1073
─────────────────────────────────────────────────────────────────────────────
Дисциплина «одна дверь» требует не ОДНОГО кода на все вопросы, а одного кода
на ОДИН вопрос. `derived_artifact_census._PathResolver` отвечает на вопрос
«какой КАТАЛОГ перечисляет этот тест, считая от корня репозитория», и для него
относительный литерал есть ОТКАЗ по делу: `"docs/decisions"` без якоря зависит
от `cwd`. Замер 28.11 на четырёх известных членах:

    INDEX_REL = f"{DECISIONS_DIR}/INDEX.md"   → `форма не разбирается: JoinedStr`
    DECISIONS_DIR = "docs/decisions"          → `относительный литерал зависит от cwd`
    os.replace(tmp, path)  (path — параметр)  → `имя в модуле не привязано`

То есть дверь ADR-1073 на МОЙ вопрос («какой путь репозитория НАЗЫВАЕТ этот
модуль») отвечает «не знаю» у ТРЁХ известных членов из четырёх. Взять её
«ради единственности» значило бы получить ответ о её вопросе и выдать его за
ответ о моём — ровно класс, против которого написана вся эта серия. Поэтому
складыватель здесь свой, узкий и объявленный:

    литерал · f-строка над уже сложенными именами · `+` · `os.path.join` ·
    цепочка `Path(якорь) / "a" / "b"` (якорь отбрасывается — путь и так
    репо-относительный) · ОДИН ХОП ЧЕРЕЗ ПАРАМЕТР (значение назначает
    вызывающий того же модуля — дверь ADR-1129 в своей форме)

Сложенное становится ПУТЁМ только если файл по нему СУЩЕСТВУЕТ в названном
дереве. Голое имя файла принимается, только если в дереве ему отвечает РОВНО
ОДИН git-видимый файл: `_BOARD.md` отвечает один, и без этой формы терялся бы
известный член ADR-1060. Двусмысленное голое имя НЕ принимается и СЧИТАЕТСЯ.

ИСХОДЫ РАЗЛИЧИМЫ (инв. #17)
─────────────────────────────────────────────────────────────────────────────
    producer_writes    мера СПРАШИВАЕТ инструмент, который ПИШЕТ путь дерева
    writes_unresolved  инструмент пишет, но цель записи не сложилась — это НЕ
                       «пересобирать нечем», это НЕ ИЗМЕРЕНО у пары
    no_write_at_all    мера спрашивает инструмент(ы), и НИ ОДИН не пишет на
                       диск вовсе (известный член — ADR-1112, базу ведут руками)
    no_producer        мера не спрашивает ни одного инструмента дерева
    unmeasured         мера не разобрана прибором класса (`unresolved`)

`writes_unresolved` к «нечем» НЕ приписывается ни одной строкой: охват общей
двери объявляется ВИЛКОЙ `producer_writes … producer_writes +
writes_unresolved`, а не одним числом (инв. #17).

Чего прибор НЕ РАЗЛИЧАЕТ и НЕ выдаёт за ответ: внутри `no_write_at_all` и
`no_producer` он НЕ отделяет «объявление ведут руками» от «объявления нет
вовсе». Для этого нужна дверь к вопросу «является ли этот путь ОЖИДАНИЕМ
меры», её здесь нет, и назвать распределение внутри было бы ответом о другом
вопросе. Это сказано вслух, а не оставлено читателю.

КОНТРОЛЬ СТАВИТ РЕЕСТР РЕШЕНИЙ, А НЕ МОЙ СПИСОК
─────────────────────────────────────────────────────────────────────────────
Закрытый перечень известных членов зелен ПО ПОСТРОЕНИЮ (ADR-1113), поэтому
полноту `CONTROL` спрашивает РЕЕСТР: каждая дверь доставки, объявленная
реестром и имеющая сторожей ВНУТРИ охвата прибора класса, обязана быть в
`CONTROL`. Реестр объявил такую дверь, а `CONTROL` о ней молчит ⇒ **НЕ
ИЗМЕРЕНО** (код 2) с её номером, а не тихое «ось в порядке».

И отдельно: ось обязана РАЗЛИЧАТЬ. Один и тот же вердикт у всех членов
контроля означает ось, которая срабатывает, но не делит, — тогда число
`producer_writes` было бы ответом о мерке. Это тоже ОТКАЗ (код 2).

Коды возврата: 0 — все меры предмета накрываются общей дверью · 1 — предмет
НАЗВАН (есть меры, которых общая дверь не накрывает) · 2 — НЕ ИЗМЕРЕНО.
Прибор только ЧИТАЕТ: ни дверей доставки, ни баз, ни `data/` не меняет.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

PRODUCER_WRITES = "producer_writes"
WRITES_UNRESOLVED = "writes_unresolved"
NO_WRITE_AT_ALL = "no_write_at_all"
NO_PRODUCER = "no_producer"
UNMEASURED = "unmeasured"

#: Вердикты оси по убыванию силы претензии. Печать идёт в этом порядке,
#: чтобы «НЕ ИЗМЕРЕНО» не пряталось в хвосте за самым многочисленным родом.
VERDICT_ORDER = (PRODUCER_WRITES, WRITES_UNRESOLVED, NO_WRITE_AT_ALL,
                 NO_PRODUCER, UNMEASURED)

#: Известные члены класса ADR-1127 и ОЖИДАЕМЫЙ вердикт оси у их сторожей.
#: Происхождение ожидания объявлено у каждой строки — «померили и закрепили»
#: и «следует из текста решения» суть разные претензии, и смешать их значило
#: бы выдать регрессионный замок за доказательство оси.
CONTROL: dict[str, dict] = {
    "ADR-889": {
        "guard": "test_adr_index_titles.py",
        "expect": PRODUCER_WRITES,
        "why": "текст задания: реестр решений пересобирает `adr_number.py titles --write`",
    },
    "ADR-1060": {
        "guard": "test_tracker_board_matches_cards.py",
        "expect": PRODUCER_WRITES,
        "why": "текст задания: доску пересобирает `build_tracker_board.py`",
    },
    "ADR-1073": {
        "guard": "test_untiered_census.py",
        "expect": PRODUCER_WRITES,
        "why": "текст задания: перепись пересобирает `audit_untiered_analytics.py --emit-markup`",
    },
    "ADR-1112": {
        "guard": "test_python_git_ref_provenance.py",
        "expect": NO_WRITE_AT_ALL,
        "why": "текст карточки дословно: «у ADR-1112 его нет вовсе — базу ведут руками»",
    },
    "ADR-150": {
        "guard": "test_adr_number_allocator.py",
        "expect": PRODUCER_WRITES,
        "why": "ИЗМЕРЕНО 28.11 и ОБЪЯСНЕНО: `adr_number.py` пишет `docs/decisions/INDEX.md`, "
               "и реестр и есть объявление интерлока номеров",
    },
    "ADR-729": {
        "guard": "test_card_section_loss_probe.py",
        "expect": PRODUCER_WRITES,
        "why": "ИЗМЕРЕНО 28.11 и это СВИДЕТЕЛЬ РЫХЛОСТИ границы: `card_acceptance.py` пишет "
               "`architecture/manifest.json` и `landing/src/data/site_numbers.json`, и ни "
               "один из них объявлением ЭТОЙ меры не является — верхняя граница охвата "
               "завышает, и завышение ИЗМЕРЕНО, а не предположено",
    },
}

#: Запись на диск. Вопрос «пишет ли инструмент ВООБЩЕ» и вопрос «какой путь он
#: пишет» РАЗНЫЕ: первый отделяет `no_write_at_all` от `writes_unresolved`,
#: второй даёт `producer_writes`. Одной мерой на оба ответить нельзя — у
#: ADR-1112 нет ни одного зова записи, и это НЕ то же самое, что «цель записи
#: не сложилась»: первое есть ОТВЕТ, второе — НЕ ИЗМЕРЕНО.
WRITE_ATTRS = frozenset({"write_text", "write_bytes"})
WRITE_FUNCS = frozenset({"atomic_save", "atomic_write"})
WRITE_MODES = ("w", "a", "x")

#: Каталоги состояния и одноразовые сцены объявлением не являются: `data/`
#: пишет живой флот, а `/tmp` исчезает вместе со сценой. Путь оттуда,
#: засчитанный объявлением, сделал бы «пересобираемо» свойством прогона.
STATE_PREFIXES = ("data/",)
SANDBOX_MARKERS = ("/tmp/", "/private/tmp/", "tmp_path", "mkdtemp", ".mutation_window/")


class NotMeasured(RuntimeError):
    """Третий исход: вопрос не задан, и это НЕ ноль."""


# ──────────────────────── свой складыватель строк ─────────────────────────

def _fold(expr: ast.expr, consts: dict, depth: int = 0) -> str | None:
    """Выражение → строка, либо `None`, если форма не сложилась.

    `consts` — привязки модуля: имя → СПИСОК выражений, которыми это имя
    связывают где угодно в модуле. Список, а не одно значение, потому что
    `out = tracker / OUT.name if args.tracker_dir else OUT` связывает имя
    ДВУМЯ путями, и годен любой, который складывается в существующий файл.
    Рекурсия ограничена: привязка, ссылающаяся на себя, обязана дать `None`,
    а не висеть.
    """
    if depth > 8:
        return None
    if isinstance(expr, ast.Constant):
        return expr.value if isinstance(expr.value, str) else None
    if isinstance(expr, ast.Name):
        for candidate in consts.get(expr.id, ()):
            if candidate is expr:
                continue
            got = _fold(candidate, consts, depth + 1)
            if got is not None:
                return got
        return None
    if isinstance(expr, ast.IfExp):
        # Обе ветви — законные значения имени, и берётся та, что сложилась в
        # БОЛЕЕ ОПРЕДЕЛЁННЫЙ путь (с каталогом). Форма ADR-1060
        # `out = tracker / OUT.name if args.tracker_dir else OUT` складывает
        # первую ветвь в голое `_BOARD.md`, а вторую — в полный путь; взять
        # первую попавшуюся значило бы положиться на то, что голому имени
        # отвечает РОВНО один файл дерева, то есть на удачу.
        got = [_fold(branch, consts, depth + 1) for branch in (expr.body, expr.orelse)]
        folded = [g for g in got if g is not None]
        if not folded:
            return None
        with_dir = [g for g in folded if "/" in g]
        return with_dir[0] if with_dir else folded[0]
    if isinstance(expr, ast.Attribute) and expr.attr in ("name", "stem"):
        base = _fold(expr.value, consts, depth + 1)
        if base is None:
            return None
        tail = pathlib.PurePosixPath(base).name
        return pathlib.PurePosixPath(tail).stem if expr.attr == "stem" else tail
    if isinstance(expr, ast.JoinedStr):
        parts = []
        for piece in expr.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                got = _fold(piece.value, consts, depth + 1)
                if got is None:
                    return None
                parts.append(got)
            else:
                return None
        return "".join(parts)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left = _fold(expr.left, consts, depth + 1)
        right = _fold(expr.right, consts, depth + 1)
        return None if left is None or right is None else left + right
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        # Цепочка `Path(якорь) / "a" / "b"`. Якорь отбрасывается НАМЕРЕННО:
        # путь репозитория и так репо-относителен, а `Path(__file__).parent`
        # сложить в строку нельзя статически ни одной формой.
        left = _fold(expr.left, consts, depth + 1)
        right = _fold(expr.right, consts, depth + 1)
        if right is None:
            return None
        return right if left is None else f"{left}/{right}".replace("//", "/")
    if isinstance(expr, ast.Call):
        func = expr.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "join" and expr.args:          # os.path.join(a, b, c)
            parts = [_fold(a, consts, depth + 1) for a in expr.args]
            if any(p is None for p in parts):
                return None
            return "/".join(p for p in parts if p is not None)
        if name in ("Path", "PurePosixPath") and expr.args:
            return _fold(expr.args[0], consts, depth + 1)
    return None


def module_consts(tree: ast.AST) -> dict:
    """Имя → список выражений, которыми его связывают ГДЕ УГОДНО в модуле.

    Область видимости здесь НАМЕРЕННО не соблюдается, и это ЗАМЕР, а не
    небрежность: цель записи доски лежит в локальной переменной `main`
    (`out = tracker / OUT.name if args.tracker_dir else OUT`), а объявление
    реестра — в модульной константе. Разбирать только модульный уровень
    значило бы потерять известного члена ADR-1060, то есть ОПРОВЕРГНУТЬ форму
    (урок ADR-1074). Цена — имя, связанное в двух местах разными путями:
    годным считается любое сложение, указывающее на СУЩЕСТВУЮЩИЙ файл, и это
    проверяется отдельной дверью (`Tree.resolve`), а не складывателем.
    """
    raw: dict[str, list] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            raw.setdefault(target.id, []).append(value)
    return raw


def _is_declaration_shaped(text: str) -> bool:
    """Строка претендует быть путём объявления (а не состоянием/сценой)."""
    if not text or "\n" in text or len(text) > 200:
        return False
    if any(marker in text for marker in SANDBOX_MARKERS):
        return False
    if text.startswith("/") or text.startswith("~"):
        return False
    if any(text.startswith(prefix) for prefix in STATE_PREFIXES):
        return False
    return text.endswith((".md", ".json", ".py", ".yaml", ".yml", ".txt", ".jsonl"))


class Tree:
    """Названное дерево и его git-видимые файлы. Голое имя разрешается ТОЛЬКО
    при единственном совпадении: двусмысленное СЧИТАЕТСЯ, а не угадывается."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        out = subprocess.run(["git", "-C", str(root), "ls-files"],
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise NotMeasured(f"git ls-files отказал в дереве {root}: {out.stderr.strip()[:200]}")
        self.tracked = set(out.stdout.split("\n")) - {""}
        self.by_name: dict[str, list] = {}
        for rel in self.tracked:
            self.by_name.setdefault(pathlib.PurePosixPath(rel).name, []).append(rel)
        self.ambiguous_names = 0

    def resolve(self, text: str) -> str | None:
        if text in self.tracked:
            return text
        hits = self.by_name.get(pathlib.PurePosixPath(text).name, [])
        if "/" in text:
            hits = [h for h in hits if h.endswith(text)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            self.ambiguous_names += 1
        return None


def named_paths(tree: ast.AST, shelf: Tree) -> set:
    """Пути репозитория, которые НАЗЫВАЕТ этот модуль (сложенные + литералы)."""
    consts = module_consts(tree)
    seen: set[str] = set()
    for bindings in consts.values():
        for value in bindings:
            text = _fold(value, consts)
            if text is not None and _is_declaration_shaped(text):
                got = shelf.resolve(text)
                if got:
                    seen.add(got)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_declaration_shaped(node.value):
                got = shelf.resolve(node.value)
                if got:
                    seen.add(got)
    return seen


# ────────────────────────────── запись на диск ─────────────────────────────

def _param_args(tree: ast.AST, func: ast.AST, name: str) -> list:
    """ОДИН ХОП ЧЕРЕЗ ПАРАМЕТР: чем вызывающие того же модуля заполняют `name`.

    Дверь ADR-1129 в своей форме: `atomic_write(path, …)` пишет `path`, и
    значение этому имени назначает не модуль, а ВЫЗЫВАЮЩИЙ. Без хопа терялся
    бы известный член ADR-1060 — то есть форма была бы ОПРОВЕРГНУТА.
    """
    args = getattr(func, "args", None)
    if args is None:
        return []
    slots = list(args.posonlyargs) + list(args.args)
    idx = next((i for i, a in enumerate(slots) if a.arg == name), None)
    if idx is None:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        called = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
        if called != getattr(func, "name", None):
            continue
        if len(node.args) > idx:
            out.append(node.args[idx])
        for kw in node.keywords:
            if kw.arg == name:
                out.append(kw.value)
    return out


def write_sites(tree: ast.AST) -> list:
    """Зовы записи модуля: `(узел_цели, объемлющая_функция)`."""
    owners: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                owners.setdefault(id(child), node)
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        target = None
        if isinstance(func, ast.Attribute) and func.attr in WRITE_ATTRS:
            target = func.value
        elif (isinstance(func, ast.Attribute) and func.attr in ("replace", "move", "copyfile")
              and len(node.args) == 2
              and isinstance(func.value, ast.Name) and func.value.id in ("os", "shutil")):
            # ХОЗЯИН ЗОВА ОБЯЗАТЕЛЕН: `текст.replace("a", "b")` — тоже `.replace`
            # с двумя аргументами, и без него у `python_git_ref_provenance.py`
            # находилось ДВА зова записи там, где их НОЛЬ. Известный член
            # ADR-1112 именно этим и отличается от прочих, то есть форма без
            # хозяина стирала разницу, на которой стоит вся ось.
            target = node.args[1]
        elif isinstance(func, ast.Name) and func.id in WRITE_FUNCS and node.args:
            target = node.args[0]
        elif isinstance(func, ast.Name) and func.id == "open" and len(node.args) >= 2:
            mode = getattr(node.args[1], "value", None)
            if isinstance(mode, str) and any(m in mode for m in WRITE_MODES):
                target = node.args[0]
        if target is not None:
            sites.append((target, owners.get(id(node))))
    return sites


def written_paths(tree: ast.AST, shelf: Tree) -> tuple:
    """`(пути, которые модуль ПИШЕТ; число зовов записи; число несложенных целей)`."""
    consts = module_consts(tree)
    sites = write_sites(tree)
    out: set[str] = set()
    unresolved = 0
    for target, owner in sites:
        texts = []
        got = _fold(target, consts)
        if got is not None:
            texts.append(got)
        elif isinstance(target, ast.Name) and owner is not None:
            for arg in _param_args(tree, owner, target.id):
                hop = _fold(arg, consts)
                if hop is not None:
                    texts.append(hop)
        hit = False
        for text in texts:
            if not _is_declaration_shaped(text):
                continue
            rel = shelf.resolve(text)
            if rel:
                out.add(rel)
                hit = True
        if not hit:
            unresolved += 1
    return out, len(sites), unresolved


# ───────────────────────────── двери и сам замер ───────────────────────────

def load_class_prober(root: pathlib.Path):
    """Прибор класса берётся ПО ПУТИ из НАЗВАННОГО дерева.

    Ввоз ПО ИМЕНИ отдал бы модуль, уже лежащий в `sys.modules`, — то есть
    перепись отвечала бы о ЧУЖОМ дереве и об этом не сказала бы ни строкой
    (ADR-796 внутри процесса, находка ADR-1127).
    """
    path = root / "scripts" / "delivery_question_census.py"
    if not path.is_file():
        raise NotMeasured(f"прибор класса не ввезён: нет файла {path}")
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("_dqc_for_rebuildable", path)
    if spec is None or spec.loader is None:
        raise NotMeasured(f"прибор класса не ввезён: спек не собран для {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"прибор класса не ввезён: {exc!r}") from exc
    finally:
        sys.modules.pop(spec.name, None)
        if sys.path and sys.path[0] == str(root / "scripts"):
            sys.path.pop(0)
    for door in ("measure", "register_doors", "_guard_producers"):
        if not hasattr(module, door):
            raise NotMeasured(f"у прибора класса нет двери `{door}`")
    return module


#: Команда пересборки внутри текста меры: `python3 scripts/X.py …`. Форма
#: узкая НАМЕРЕННО — см. `guard_tools`.
REBUILD_COMMAND = re.compile(r"python3?\s+(?:-m\s+)?([A-Za-z0-9_./-]+\.py)\b")


def guard_tools(shelf: Tree, tree: ast.AST, asked, self_rel: str) -> dict:
    """Инструменты, которые СПРАШИВАЕТ эта мера: путь → чем он опознан.

    ДВЕРЕЙ ДВЕ, И КАЖДУЮ ПОТРЕБОВАЛ ИЗВЕСТНЫЙ ЧЛЕН, а не вкус автора:

    1. **ответ прибора класса** (`producers` у записи поверхности) — так назван
       производитель, которого сторож ЗОВЁТ. Один он ТЕРЯЕТ ADR-889: у
       `test_adr_index_titles.py` прибор класса отвечает `producers=[]`, потому
       что инструмент ввозится через локального помощника `_load(...)`.
    2. **команда пересборки в тексте меры** (`python3 scripts/X.py …`) — так
       мера сама называет, чем её объявление чинят. Одна она ТЕРЯЕТ ADR-1073:
       `test_untiered_census.py` команды не несёт вовсе.

    Форма «любое имя `*.py` строкой» ОПРОВЕРГНУТА замером 28.11: у
    `test_python_git_ref_provenance.py` она добирала `scripts/check_owner_gate.py`
    (строка СЦЕНЫ: `file="scripts/check_owner_gate.py"`) и голые `a.py`/`b.py`
    из `docs/evidence/...`, и известный член ADR-1112 уходил из `no_write_at_all`
    в `writes_unresolved` — то есть форма стирала ровно ту разницу, на которой
    стоит ось. Упоминание инструмента данными сцены НЕ есть «мера его
    спрашивает».

    Голое имя файла здесь НЕ разрешается (в отличие от объявления): инструмент
    обязан быть назван путём под `scripts/` или `spa_core/`.
    """
    out: dict[str, str] = {}

    def _add(rel: str | None, how: str) -> None:
        if not rel or rel == self_rel or not rel.endswith(".py"):
            return
        if not (rel.startswith("scripts/") or rel.startswith("spa_core/")):
            return
        if pathlib.PurePosixPath(rel).name.startswith("test_") or "/tests/" in rel:
            return
        out.setdefault(rel, how)

    for name in asked or ():
        hits = [c for c in (f"scripts/{name}",) if c in shelf.tracked]
        if not hits:
            hits = [p for p in shelf.by_name.get(name, []) if p.startswith("spa_core/")]
        if len(hits) == 1:
            _add(hits[0], "прибор класса: мера ЗОВЁТ")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in REBUILD_COMMAND.finditer(node.value):
                candidate = match.group(1)
                if candidate in shelf.tracked:
                    _add(candidate, "команда пересборки в тексте меры")
    return out


def measure(root: pathlib.Path) -> dict:
    dqc = load_class_prober(root)
    try:
        klass = dqc.measure(root)
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"класс не измерен: {exc}") from exc

    shelf = Tree(root)
    cache: dict[str, dict] = {}

    def tool(rel_path: pathlib.Path) -> dict:
        key = str(rel_path)
        if key not in cache:
            try:
                tree = ast.parse(rel_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                cache[key] = {"error": repr(exc)}
                return cache[key]
            writes, sites, unresolved = written_paths(tree, shelf)
            cache[key] = {"names": named_paths(tree, shelf), "writes": writes,
                          "sites": sites, "unresolved": unresolved}
        return cache[key]

    measures = []
    for guard in klass["guards"]:
        rel = guard["path"]
        if guard["verdict"] == dqc.UNMEASURED:
            measures.append({"path": rel, "class": dqc.UNMEASURED, "verdict": UNMEASURED,
                             "reason": guard.get("reason", ""), "declaration": None,
                             "writer": None})
            continue
        guard_file = root / rel
        try:
            tree = ast.parse(guard_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            measures.append({"path": rel, "class": guard["verdict"], "verdict": UNMEASURED,
                             "reason": f"сторож не разобран: {exc!r}", "declaration": None,
                             "writer": None})
            continue
        tools = guard_tools(shelf, tree, guard.get("producers") or [], rel)
        write_sites_seen = 0
        unresolved_targets = 0
        rebuilt: tuple | None = None
        for tool_rel in sorted(tools):
            info = tool(root / tool_rel)
            if "error" in info:
                continue
            write_sites_seen += info["sites"]
            unresolved_targets += info["unresolved"]
            written = sorted(info["writes"])
            if written and rebuilt is None:
                rebuilt = (written[0], tool_rel)
        if rebuilt:
            verdict, reason = PRODUCER_WRITES, ""
            declaration, writer = rebuilt
        elif write_sites_seen:
            verdict = WRITES_UNRESOLVED
            reason = (f"спрошенный инструмент пишет ({write_sites_seen} зов(ов), цель не "
                      f"сложилась у {unresolved_targets}) — это НЕ «пересобирать нечем», "
                      "это НЕ ИЗМЕРЕНО у пары")
            declaration, writer = None, None
        elif tools:
            verdict = NO_WRITE_AT_ALL
            reason = ("мера спрашивает инструмент(ы), и НИ ОДИН не пишет на диск вовсе — "
                      "объявление, если оно есть, ведут руками")
            declaration, writer = None, None
        else:
            verdict = NO_PRODUCER
            reason = "мера не спрашивает ни одного инструмента дерева — пересобирать нечем"
            declaration, writer = None, None
        measures.append({"path": rel, "class": guard["verdict"], "verdict": verdict,
                         "reason": reason, "declaration": declaration, "writer": writer,
                         "tools": sorted(tools)[:6]})

    by_path = {m["path"]: m for m in measures}

    # ── контроль: полноту перечня ставит РЕЕСТР, а не мой список ──
    declared, register_read = dqc.register_doors(root)
    control: dict[str, dict] = {}
    missing: list[str] = []
    for number, info in sorted(declared.items()):
        inside = [g for g in info["guards"] if f"spa_core/tests/{g}" in by_path]
        if not inside:
            control[number] = {"state": "вне охвата прибора класса — граница ОХВАТА"}
            continue
        if number not in CONTROL:
            missing.append(number)
            continue
        want = CONTROL[number]
        rel = f"spa_core/tests/{want['guard']}"
        if rel not in by_path:
            missing.append(f"{number} (сторож {want['guard']} вне поверхности)")
            continue
        got = by_path[rel]["verdict"]
        control[number] = {"guard": want["guard"], "expect": want["expect"],
                           "got": got, "why": want["why"], "ok": got == want["expect"]}
    if missing:
        raise NotMeasured(
            "реестр объявил дверь доставки со сторожами ВНУТРИ охвата, а контроль о ней "
            f"молчит: {', '.join(missing)} — закрытый перечень был бы зелен по построению"
        )
    broken = {n: c for n, c in control.items() if c.get("ok") is False}
    if broken:
        raise NotMeasured(
            "ось не подтверждена известными членами: "
            + " · ".join(f"{n}: ждали {c['expect']}, вышло {c['got']}" for n, c in broken.items())
        )
    distinct = {c["got"] for c in control.values() if "got" in c}
    if len(distinct) < 2:
        raise NotMeasured(
            f"ось НЕ РАЗЛИЧАЕТ: у всех известных членов один вердикт {sorted(distinct)} — "
            "число пересобираемых было бы ответом о мерке, а не о классе"
        )

    counts: dict[str, dict] = {}
    for item in measures:
        slot = counts.setdefault(item["class"], {})
        slot[item["verdict"]] = slot.get(item["verdict"], 0) + 1
    subject = counts.get(dqc.SUBJECT, {})
    closable = subject.get(PRODUCER_WRITES, 0)
    return {
        "root": str(root),
        "register_read": register_read,
        "class_counts": klass["counts"],
        "counts": counts,
        "control": control,
        "control_distinct": sorted(distinct),
        "ambiguous_bare_names": shelf.ambiguous_names,
        "subject_total": sum(subject.values()),
        "general_door_covers": closable,
        "measures": measures,
        "code": 1 if sum(subject.values()) - closable else 0,
    }


def render(report: dict, names: bool, limit: int) -> str:
    subject = report["counts"].get("subject", {})
    total = report["subject_total"]
    covers = report["general_door_covers"]
    out = [
        f"дерево: {report['root']}  (ВЫБОР НАПЕЧАТАН, не угадан)",
        "реестр решений (полноту контроля ставит он): " + " · ".join(report["register_read"]),
        f"класс ADR-1127 в этом дереве: " + " · ".join(
            f"{k}={v}" for k, v in sorted(report["class_counts"].items())),
        "",
        f"ПРЕДМЕТ класса — {total} мер(ы). Пересобираемость их объявления:",
    ]
    for verdict in VERDICT_ORDER:
        if verdict in subject:
            out.append(f"   {verdict:<18} {subject[verdict]}")
    unreachable = subject.get(NO_WRITE_AT_ALL, 0) + subject.get(NO_PRODUCER, 0)
    unknown = subject.get(WRITES_UNRESOLVED, 0)
    out.append("")
    out.append(f"⇒ ОБЩАЯ ДВЕРЬ накрывает НЕ БОЛЬШЕ {covers} из {total} мер предмета "
               f"({100.0 * covers / total:.1f} %) — и это ВЕРХНЯЯ граница, завышенная: "
               "засчитан любой спрошенный инструмент, который пишет ХОТЬ КАКОЙ-ТО путь "
               "дерева, а объявлением этой меры он быть не обязан (измеренный свидетель — "
               "ADR-729 в контроле ниже)")
    out.append(f"⇒ НЕ накрывается ТОЧНО: {unreachable} из {total} "
               f"({100.0 * unreachable / total:.1f} %) — пересобирать нечем, потому что "
               "либо спрошенный инструмент не пишет на диск вовсе, либо инструмента мера "
               "не спрашивает ни одного")
    out.append(f"⚠️ НЕ ИЗМЕРЕНО: {unknown} из {total} — инструмент пишет, цель записи не "
               "сложилась. Нулём это не считается и к «нечем» НЕ приписывается: охват "
               f"общей двери есть ВИЛКА {covers} … {covers + unknown}")
    out.append("   НЕ РАЗЛИЧАЕТСЯ внутри `no_write_at_all`/`no_producer`: «объявление ведут "
               "руками» против «объявления нет вовсе» — для этого нужна дверь к вопросу "
               "«является ли путь ОЖИДАНИЕМ меры», её здесь нет")
    if report["ambiguous_bare_names"]:
        out.append(f"   голых имён, которым отвечает не один файл: "
                   f"{report['ambiguous_bare_names']} — не угаданы, а СОЧТЕНЫ")
    out.append("")
    out.append("положительный контроль (полноту перечня ставит РЕЕСТР):")
    for number, info in sorted(report["control"].items()):
        if "got" in info:
            mark = "✅" if info["ok"] else "❌"
            out.append(f"  {mark} {number}: {info['guard']} → {info['got']} "
                       f"(ждали {info['expect']}) · {info['why']}")
        else:
            out.append(f"  · {number}: {info['state']}")
    out.append(f"  ось РАЗЛИЧАЕТ: вердиктов у контроля {len(report['control_distinct'])} "
               f"({', '.join(report['control_distinct'])})")
    for other, slot in sorted(report["counts"].items()):
        if other == "subject":
            continue
        out.append(f"  (для сверки) класс `{other}`: " + " · ".join(
            f"{k}={v}" for k, v in sorted(slot.items())))
    if names:
        out.append("")
        out.append(f"предмет поимённо (предел {limit}):")
        shown = [m for m in report["measures"]
                 if m["class"] == "subject" and m["verdict"] != PRODUCER_WRITES]
        for item in shown[:limit]:
            out.append(f"  {item['verdict']:<18} {item['path']}")
        if len(shown) > limit:
            out.append(f"  … ещё {len(shown) - limit}")
    out.append("— прибор только ЧИТАЕТ: ни дверей доставки, ни баз, ни data/ не меняет —")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--repo-root", default=None, help="дерево, которое мерить")
    parser.add_argument("--names", action="store_true", help="печатать предмет поимённо")
    parser.add_argument("--limit", type=int, default=20, help="предел печати предмета")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.repo_root:
        root = pathlib.Path(args.repo_root).expanduser().resolve()
        if not root.is_dir():
            print(f"НЕ ИЗМЕРЕНО: названное дерево не читается: {root}", file=sys.stderr)
            return 2
    else:
        root = pathlib.Path(__file__).resolve().parent.parent
        print(f"дерево НЕ НАЗВАНО — беру дерево прибора: {root}", file=sys.stderr)

    try:
        report = measure(root)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(report, args.names, args.limit))
    return report["code"]


if __name__ == "__main__":
    sys.exit(main())
