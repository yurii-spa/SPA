"""Односторонность правила принадлежности — ИЗМЕРЕНА, а не объявлена (заказ G87 п. 2).

ADR-491 очертил население критерия §49 `No regression` по тому, что тест
ИМПОРТИРУЕТ, и честно назвал односторонность вслух:

> «правило видит только объявленное имя, поэтому тест, трогающий поверхность
> через промежуточный помощник, в население не попадёт. Мера ошибается в сторону
> ЗАНИЖЕНИЯ».

Названо — но не посчитано. Заказ G87 п. 2 требует именно числа: **сколько тестов
трогают risk/security/architecture через помощника**, мерить транзитивным
замыканием по дереву импортов, с НАЗВАННЫМ пределом глубины и третьим исходом на
неразрешённое имя; результат — НИЖНЯЯ граница, и она обязана называться нижней.

Разница между «объявлено» и «измерено» здесь не академическая. Вердикт критерия
§49 звучит как «существующие risk/security/architecture-тесты проходят». Если
половина таких тестов в население не входит, зелёный вердикт получается не из
исправности дерева, а из слепоты правила — ровно тот дефект, который ADR-491
дважды переписывал у себя же (`test_risk_policy.py` терялся из-за второго
написания пакета, живой красный architecture-тест — из-за непрозрачного импорта).

## Что мерится и чем

**Правило принадлежности НЕ переписывается здесь второй раз.** Имена импортов
читает тот же `_imported_modules`, сопоставляет с префиксами тот же `_matches`,
поверхности берутся из того же `DECLARED_SURFACES` соседа. Вторая копия правила
и есть дефект, который ловит ADR-522: разойдясь, две копии молча дали бы два
разных населения у одного критерия.

Прибор добавляет к правилу соседа ровно одно — **дорогу**:

* **граф импортов всего дерева** (узел — файл `.py`, дуга — импорт, разрешённый
  в файл этого же дерева), и по нему обратный обход в ширину от поверхности;
* **относительный импорт**. Сосед его пропускает НАМЕРЕННО и по верной причине:
  у `from . import policy` нет имени, которое можно сопоставить с объявленным
  префиксом, а выдумывать имя значило бы завести второй способ принадлежности.
  В замыкании имя выдумывать не нужно: у файла есть ПУТЬ, из пути дуга
  разрешается арифметикой каталогов, а точечное имя выводится из места файла в
  дереве — это наблюдение, а не догадка.

## Две оси, каждый перечень ЗАКРЫТ (инв. #17)

**Ось пары «тест × поверхность»** — сумма обязана равняться населению:

* `surface_imported_directly` — правило соседа видит пару уже сегодня (глубина
  0 либо объявление путём `self_guards`). Слепоты здесь нет;
* `surface_reached_through_helper` — **НАХОДКА**: поверхность достигается только
  через помощника, на глубине от 1 до объявленного предела;
* `reached_beyond_declared_depth` — третий исход: дорога ЕСТЬ, но длиннее
  объявленного предела. Находкой это не объявляется и «чистым» тоже: на
  достаточной глубине в нашем дереве всё достигает всего, и назвать это
  «тест трогает risk-логику» значило бы заменить измерение словом. Поэтому
  предел назван числом, а цена предела напечатана рядом;
* `surface_not_reached` — дорога не найдена вовсе.

**Ось ИМЕНИ** (в сумму населения НЕ входит) — что стало с каждым именем, которое
встретилось при обходе:

* `name_resolved_in_tree` — разрешилось в файл дерева, дуга пройдена;
* `name_attribute_of_resolved_module` — имя целиком не файл, но его префикс
  файл: `from a.b import C` даёт и `a.b`, и `a.b.C`; второе есть атрибут, и
  слепоты в нём нет — префикс пройден;
* `name_outside_tree` — верхний уровень имени не является именем верхнего уровня
  нашего дерева (stdlib или сторонний пакет). Дуга НЕ пройдена. Это объявленная
  односторонность: сторонний модуль, импортирующий нашу risk-логику, мерой не
  виден;
* `name_unresolved` — **третий исход на имя**: верхний уровень наш, а файла нет
  ни у имени, ни у одного его префикса. Такая дуга могла вести к поверхности, и
  потому ответ «не достигает» односторонен.

## Почему «не достигает» есть НИЖНЯЯ граница — и с какой стороны

Число находок ошибается в сторону ЗАНИЖЕНИЯ вреда по трём названным причинам:
дуги за пределом глубины, дуги через сторонний модуль и неразрешённые имена.
Поэтому `surface_reached_through_helper` печатается как нижняя граница, а не как
ответ, и рядом печатаются все три цены. Односторонний ноль обязан называться
нижней границей (урок ADR-528).

## Контроль, который прибор несёт сам

`parity_with_census`: множество пар `surface_imported_directly` сверяется с
населением соседа, посчитанным его собственной функцией `population()`. Равенство
— доказательство, что дорога добавлена К правилу, а не ВМЕСТО него; расхождение
печатается числом. Сверка сама с собой была бы зелёной по построению (урок
цикла #722), поэтому сверяются ДВА независимо посчитанных множества.

## ADVISORY

Прибор только ЧИТАЕТ дерево: ни одного теста не запускает, не правит и не
ослабляет (инв. #16); RiskPolicy v1.0, стоп-кран, аллокатор, гейт исполнения,
живой трек, `landing/**` и флот не трогаются. LLM запрещён (инв. #3). Ввозы —
только stdlib (инв. #4). Артефакта прибор НАМЕРЕННО не производит: читателем
служит шаг 0-офис, зовущий `measure()` напрямую, — тот же порядок и та же
причина, что у ADR-524 (артефакт переписи стал бы собственным операндом
«предыдущего прогона», то есть новым членом измеряемого класса).

Время, pid, сеть и git-окружение прибор не спрашивает ни у машины, ни у часов:
единственный вход — путь дерева, поэтому мера проверяется фикстурой
(`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
import os
import pathlib
import sys

from spa_core.monitoring.no_regression_census import (
    DECLARED_SURFACES,
    TEST_ROOTS,
    _imported_modules,
    _matches,
    population as census_population,
)

# ── ось пары «тест × поверхность». Перечень ЗАКРЫТ: сумма = население ────────
DIRECT = "surface_imported_directly"
VIA_HELPER = "surface_reached_through_helper"
BEYOND = "reached_beyond_declared_depth"
NOT_REACHED = "surface_not_reached"

OUTCOMES: tuple[str, ...] = (DIRECT, VIA_HELPER, BEYOND, NOT_REACHED)

# ── ось ИМЕНИ. Отдельная ось, в сумму населения НЕ входит ────────────────────
NAME_IN_TREE = "name_resolved_in_tree"
NAME_ATTR = "name_attribute_of_resolved_module"
NAME_OUTSIDE = "name_outside_tree"
NAME_UNRESOLVED = "name_unresolved"

NAME_OUTCOMES: tuple[str, ...] = (NAME_IN_TREE, NAME_ATTR, NAME_OUTSIDE,
                                  NAME_UNRESOLVED)

#: Предел глубины замыкания — ВЫБОР, объявленный числом, а не свойство дерева.
#: Причина предела: в нашем дереве почти всё достигает почти всего, если идти
#: достаточно далеко, и объявить такую дорогу «тест трогает risk-логику» значило
#: бы заменить измерение словом. Цена предела печатается рядом с вердиктом
#: (`reached_beyond_declared_depth`), поэтому выбор виден читателю, а не спрятан.
MAX_DEPTH = 3

#: Каталоги, которые в граф импортов не входят: внутри них нет нашего кода, а
#: разбор стоит минуты. Перечень объявлен — молчаливое сужение дерева было бы
#: тем же, чем сужение прогона «до своего набора» (цикл #189).
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", "site-packages",
})

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Unmeasured(RuntimeError):
    """Предпосылка переписи не обеспечена. Третий исход, а не ноль."""


# ───────────────────────────── разрешение имён ────────────────────────────────

def _search_roots(root: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """Корни, относительно которых разрешается точечное имя.

    Их ДВА по той же причине, по которой у соседа два написания префикса: тесты
    кладут в ``sys.path`` либо корень репозитория, либо ``spa_core/``. Знать один
    корень значит терять половину дуг, и это замер соседа, а не гипотеза.
    """
    return (root, root / "spa_core")


def _top_level_names(root: pathlib.Path) -> frozenset[str]:
    """Имена верхнего уровня, которые принадлежат ЭТОМУ дереву.

    Нужны, чтобы развести «сторонний модуль» (дугу не идём, и это объявленная
    односторонность) от «наше имя, а файла нет» (третий исход на имя).
    """
    out: set[str] = set()
    for base in _search_roots(root):
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if entry.name.startswith(".") or entry.name in _SKIP_DIRS:
                continue
            if entry.is_dir():
                out.add(entry.name)
            elif entry.suffix == ".py":
                out.add(entry.stem)
    return frozenset(out)


def _resolve(root: pathlib.Path, dotted: str,
             cache: dict[str, str | None]) -> str | None:
    """Путь файла (относительно корня) для точечного имени. ``None`` = нет файла."""
    if dotted in cache:
        return cache[dotted]
    parts = dotted.split(".")
    found: str | None = None
    if all(parts) and not any(p.startswith(".") for p in parts):
        for base in _search_roots(root):
            stem = base.joinpath(*parts)
            for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
                if candidate.is_file():
                    found = candidate.relative_to(root).as_posix()
                    break
            if found:
                break
    cache[dotted] = found
    return found


def _attribute_candidates(tree: ast.AST) -> set[str]:
    """Имена, которые МОГУТ быть атрибутом, а не модулем.

    Различие существенно и было найдено контролем, а не рассуждением:
    ``from a.b import C`` даёт имя ``a.b.C``, которое вправе оказаться
    атрибутом, — а ``import a.b`` требует МОДУЛЯ, и неразрешённое имя здесь
    есть настоящий третий исход. Сосед отдаёт плоское множество имён, в котором
    формы не различить; считать обе формы атрибутом значило бы погасить третий
    исход молча — ровно то, ради чего заказ его и требует.

    Правило принадлежности этим не переписывается: имена по-прежнему добывает
    ``_imported_modules`` соседа, здесь спрашивается только ФОРМА.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                out.add(f"{node.module}.{alias.name}")
    return out


def _classify_name(root: pathlib.Path, dotted: str, top_levels: frozenset[str],
                   cache: dict[str, str | None],
                   attribute_candidates: frozenset[str] = frozenset(),
                   ) -> tuple[str, str | None]:
    """Исход для одного имени оси ИМЕНИ + файл, если дуга проходима."""
    rel = _resolve(root, dotted, cache)
    if rel is not None:
        return NAME_IN_TREE, rel
    head = dotted.split(".")[0]
    if head not in top_levels:
        return NAME_OUTSIDE, None
    # Наше имя верхнего уровня, а файла у полного имени нет. Атрибутом оно
    # вправе быть ТОЛЬКО если пришло формой `from … import …` и файл есть у
    # префикса: тогда префикс пройден отдельным членом того же набора.
    parts = dotted.split(".")
    if dotted in attribute_candidates:
        for cut in range(len(parts) - 1, 0, -1):
            if _resolve(root, ".".join(parts[:cut]), cache) is not None:
                return NAME_ATTR, None
    return NAME_UNRESOLVED, None


def _dotted_spellings(rel: str) -> tuple[str, ...]:
    """Точечные имена файла, ВЫВЕДЕННЫЕ из его места в дереве.

    Два написания по той же причине, что у соседа два префикса: файл
    ``spa_core/risk/policy.py`` для одного теста зовётся ``spa_core.risk.policy``,
    для другого — ``risk.policy``. Это не догадка об имени, а следствие пути.
    """
    parts = rel[: -len(".py")].split("/") if rel.endswith(".py") else rel.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return ()
    full = ".".join(parts)
    out = [full]
    if parts[0] == "spa_core" and len(parts) > 1:
        out.append(".".join(parts[1:]))
    return tuple(out)


# ───────────────────────────── граф импортов ─────────────────────────────────

def _relative_edges(tree: ast.AST, rel: str,
                    root: pathlib.Path) -> list[str]:
    """Файлы, в которые ведут ОТНОСИТЕЛЬНЫЕ импорты файла ``rel``.

    Сосед их пропускает намеренно (имени нет). Здесь имя и не нужно: дуга
    разрешается арифметикой каталогов от места самого файла.
    """
    here = pathlib.PurePosixPath(rel).parent
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        base = here
        for _ in range(node.level - 1):
            base = base.parent
        anchor = base.joinpath(*node.module.split(".")) if node.module else base
        targets = [anchor]
        targets += [anchor / alias.name for alias in node.names]
        for target in targets:
            for candidate in (root / f"{target}.py", root / target / "__init__.py"):
                if candidate.is_file():
                    out.append(candidate.relative_to(root).as_posix())
                    break
    return out


def _py_files(root: pathlib.Path) -> list[str]:
    """Все файлы ``.py`` дерева, кроме объявленных пропускаемых каталогов."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                full = pathlib.Path(dirpath) / name
                out.append(full.relative_to(root).as_posix())
    return sorted(out)


def build_graph(repo_root: str) -> dict:
    """Граф импортов дерева + ось ИМЕНИ. Единственный вход — путь дерева."""
    root = pathlib.Path(repo_root)
    if not root.is_dir():
        raise Unmeasured(f"дерева нет по пути {repo_root}")
    files = _py_files(root)
    if not files:
        raise Unmeasured(f"ни одного файла .py в дереве {repo_root}")
    top_levels = _top_level_names(root)
    resolve_cache: dict[str, str | None] = {}

    declares: dict[str, set[str]] = {}
    edges: dict[str, set[str]] = {}
    name_counts = {name: 0 for name in NAME_OUTCOMES}
    unresolved_names: dict[str, int] = {}
    unparsed: dict[str, str] = {}
    relative_edges_resolved = 0

    for rel in files:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
            unparsed[rel] = f"{type(exc).__name__}: {exc}"
            continue
        names = _imported_modules(tree)
        attributes = frozenset(_attribute_candidates(tree))
        targets: set[str] = set()
        for dotted in sorted(names):
            outcome, target = _classify_name(root, dotted, top_levels,
                                             resolve_cache, attributes)
            name_counts[outcome] += 1
            if outcome == NAME_UNRESOLVED:
                unresolved_names[dotted] = unresolved_names.get(dotted, 0) + 1
            if target is not None:
                targets.add(target)
        declared = set(names)
        for target in _relative_edges(tree, rel, root):
            relative_edges_resolved += 1
            targets.add(target)
            # Имя выводится из ПУТИ файла, а не выдумывается: сопоставление с
            # префиксом поверхности без него было бы невозможно, и дуга
            # относительного импорта в risk-пакет считалась бы ненайденной.
            declared.update(_dotted_spellings(target))
        declares[rel] = declared
        edges[rel] = targets

    return {
        "files": files,
        "declares": declares,
        "edges": edges,
        "name_counts": name_counts,
        "unresolved_names": unresolved_names,
        "unparsed": unparsed,
        "relative_edges_resolved": relative_edges_resolved,
        "top_levels": sorted(top_levels),
    }


def _distances(graph: dict, prefixes: tuple[str, ...]) -> tuple[dict[str, int],
                                                               dict[str, str]]:
    """Кратчайшее число дуг от файла до поверхности + первый шаг дороги.

    Обход в ширину по ОБРАЩЁННОМУ графу от семян (файлов, объявляющих имя
    поверхности сами). Расстояние точное: граф конечен, и обход доходит до
    конца — поэтому предел глубины остаётся ВЫБОРОМ отчёта, а не обрывом
    измерения, выданным за «дороги нет».
    """
    declares = graph["declares"]
    edges = graph["edges"]
    reverse: dict[str, list[str]] = collections.defaultdict(list)
    for src, targets in edges.items():
        for dst in targets:
            reverse[dst].append(src)

    dist: dict[str, int] = {}
    hop: dict[str, str] = {}
    queue: collections.deque[str] = collections.deque()
    for rel, names in declares.items():
        if _matches(set(names), prefixes):
            dist[rel] = 0
            queue.append(rel)
    while queue:
        node = queue.popleft()
        for parent in reverse.get(node, ()):
            if parent in dist:
                continue
            dist[parent] = dist[node] + 1
            hop[parent] = node
            queue.append(parent)
    return dist, hop


def _chain(start: str, hop: dict[str, str], limit: int = 8) -> list[str]:
    """Дорога от теста до поверхности — поимённо, чтобы находку можно было открыть."""
    out = [start]
    node = start
    while node in hop and len(out) <= limit:
        node = hop[node]
        out.append(node)
    return out


def _test_files(repo_root: str,
                graph: dict) -> tuple[list[str], list[str], list[str]]:
    """Тест-файлы предписанных каталогов — ТРЕМЯ исходами, а не двумя.

    Третий исход найден мутационным замером, а не рассуждением: обход теста
    (``rglob``) и обход графа (``os.walk`` с перечнем пропуска) видят РАЗНЫЕ
    множества, поэтому файл вида ``spa_core/tests/__pycache__/test_x.py``
    находится первым и отсутствует во втором. Прежняя редакция роняла такой
    файл МОЛЧА — то есть «не измерено» становилось неотличимо от «не достигает»
    (инв. #17). Теперь он называется.
    """
    root = pathlib.Path(repo_root)
    parsed: list[str] = []
    unparsed: list[str] = []
    outside_graph: list[str] = []
    for rel_root in TEST_ROOTS:
        base = root / rel_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in graph["unparsed"]:
                unparsed.append(rel)
            elif rel in graph["declares"]:
                parsed.append(rel)
            else:
                outside_graph.append(rel)
    return parsed, unparsed, outside_graph


# ──────────────────────────────── перепись ───────────────────────────────────

def measure(repo_root: str = REPO_ROOT, max_depth: int = MAX_DEPTH,
            graph: dict | None = None) -> dict:
    """Перепись «дотягивается ли тест до поверхности через помощника».

    ``graph`` — ВХОД: так прибор проверяется фикстурой, а не живым деревом.
    ``max_depth`` — объявленный предел, а не свойство дерева.
    """
    try:
        graph = graph if graph is not None else build_graph(repo_root)
    except Unmeasured as exc:
        return {
            "population": 0,
            "max_depth": max_depth,
            "counts": {name: 0 for name in OUTCOMES},
            "name_counts": {name: 0 for name in NAME_OUTCOMES},
            "findings": [],
            "depth_histogram": {},
            "per_surface": {},
            "unparsed_tests": [],
            "tests_outside_the_graph": [],
            "unresolved_examples": [],
            "relative_edges_resolved": 0,
            "parity_with_census": None,
            "files_in_graph": 0,
            "unmeasured_reason": str(exc),
        }

    tests, unparsed_tests, outside_graph = _test_files(repo_root, graph)
    counts = {name: 0 for name in OUTCOMES}
    per_surface: dict[str, dict] = {}
    findings: list[dict] = []
    depth_histogram: dict[str, int] = {}
    direct_pairs: set[tuple[str, str]] = set()

    for surface, spec in DECLARED_SURFACES.items():
        dist, hop = _distances(graph, spec["modules"])  # type: ignore[arg-type]
        guards = frozenset(spec["self_guards"])  # type: ignore[arg-type]
        local = {name: 0 for name in OUTCOMES}
        for rel in tests:
            depth = dist.get(rel)
            if rel in guards or depth == 0:
                outcome = DIRECT
                direct_pairs.add((rel, surface))
            elif depth is None:
                outcome = NOT_REACHED
            elif depth <= max_depth:
                outcome = VIA_HELPER
                findings.append({"file": rel, "surface": surface, "depth": depth,
                                 "chain": _chain(rel, hop)})
                key = str(depth)
                depth_histogram[key] = depth_histogram.get(key, 0) + 1
            else:
                outcome = BEYOND
            local[outcome] += 1
            counts[outcome] += 1
        per_surface[surface] = local

    return {
        "population": len(tests) * len(DECLARED_SURFACES),
        "tests_scanned": len(tests),
        "surfaces": sorted(DECLARED_SURFACES),
        "max_depth": max_depth,
        "counts": counts,
        "per_surface": per_surface,
        "name_counts": dict(graph["name_counts"]),
        "findings": sorted(findings, key=lambda row: (row["depth"], row["surface"],
                                                      row["file"])),
        "depth_histogram": depth_histogram,
        "unparsed_tests": unparsed_tests,
        "tests_outside_the_graph": outside_graph,
        "unresolved_examples": sorted(graph["unresolved_names"],
                                      key=lambda n: (-graph["unresolved_names"][n], n))[:8],
        "relative_edges_resolved": graph["relative_edges_resolved"],
        "parity_with_census": _parity(repo_root, direct_pairs),
        "files_in_graph": len(graph["declares"]),
        "unmeasured_reason": "",
    }


def _parity(repo_root: str, direct_pairs: set[tuple[str, str]]) -> dict | None:
    """Сверка множества «видно соседу» с населением, посчитанным САМИМ соседом.

    Контроль того, что дорога добавлена К правилу, а не ВМЕСТО него. Сверять
    свою копию с собой было бы зелено по построению (урок #722), поэтому здесь
    зовётся ``population()`` соседа — независимый счёт того же множества.
    """
    try:
        doc = census_population(repo_root)
    except Exception as exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
        return {"state": "unmeasured", "why": f"{type(exc).__name__}: {exc}"}
    theirs = {(rel, surface)
              for surface, data in doc["surfaces"].items()
              for rel in data["files"]}
    only_mine = sorted(f"{rel}::{s}" for rel, s in direct_pairs - theirs)
    only_theirs = sorted(f"{rel}::{s}" for rel, s in theirs - direct_pairs)
    return {
        "state": "equal" if not only_mine and not only_theirs else "differs",
        "census_pairs": len(theirs),
        "direct_pairs": len(direct_pairs),
        "only_here": only_mine[:8],
        "only_in_census": only_theirs[:8],
        "n_only_here": len(only_mine),
        "n_only_in_census": len(only_theirs),
    }


def verdict(doc: dict) -> str:
    if doc.get("unmeasured_reason") or not doc.get("population"):
        return "unmeasured"
    return ("rule_is_one_sided" if doc["counts"][VIA_HELPER]
            else "no_helper_reach_found")


def format_report(doc: dict) -> str:
    """Отчёт для шага 0-офис. Каждый ноль объявлен (инв. #17)."""
    if doc.get("unmeasured_reason"):
        return ("НЕ ИЗМЕРЕНО: односторонность правила принадлежности — "
                f"{doc['unmeasured_reason']}")
    if not doc.get("population"):
        # Пустое население печаталось бы как «все нули», то есть как ЧИСТО —
        # это fail-OPEN тише красного теста (урок `pyflakes`, #465).
        return ("НЕ ИЗМЕРЕНО: односторонность правила принадлежности — ни одного "
                "разобранного тест-файла в предписанных каталогах; ноль исходов "
                "на пустом населении не есть «чисто»")
    counts = doc["counts"]
    lines = [f"односторонность правила принадлежности (заказ G87 п. 2): население "
             f"{doc['population']} пар(ы) «тест × поверхность» "
             f"({doc['tests_scanned']} тест(ов) × {len(doc['surfaces'])} поверхност(и)), "
             f"предел глубины {doc['max_depth']} (ВЫБОР, не свойство дерева)"]
    lines.append("  " + " · ".join(f"{name} {counts[name]}" for name in OUTCOMES))
    reachable = counts[DIRECT] + counts[VIA_HELPER] + counts[BEYOND]
    share = f"{counts[DIRECT] / reachable * 100:.1f} %" if reachable else "НЕ ИЗМЕРЕНО"
    lines.append(f"  ОТВЕТ заказа: дорог до поверхности найдено {reachable}, правило "
                 f"соседа видит {counts[DIRECT]} из них ({share}); "
                 f"остальные {reachable - counts[DIRECT]} идут через помощника и в "
                 "население критерия §49 не входят")
    lines.append("  по поверхностям: " + " · ".join(
        f"{s}: прямо {d[DIRECT]}, через помощника {d[VIA_HELPER]}"
        for s, d in sorted(doc["per_surface"].items())))
    names = doc["name_counts"]
    lines.append("  ось ИМЕНИ (в сумму НЕ входит): " + " · ".join(
        f"{name} {names.get(name, 0)}" for name in NAME_OUTCOMES)
        + f"; дуг относительного импорта разрешено {doc['relative_edges_resolved']}"
          f" (сосед их не видит по построению); файлов в графе {doc['files_in_graph']}")
    if doc["depth_histogram"]:
        lines.append("  глубина находок: " + " · ".join(
            f"{k} дуг(а): {v}" for k, v in sorted(doc["depth_histogram"].items())))
    for row in doc["findings"][:12]:
        lines.append(f"  [{VIA_HELPER}] {row['file']} → {row['surface']} "
                     f"(глубина {row['depth']}): " + " → ".join(row["chain"]))
    if len(doc["findings"]) > 12:
        lines.append(f"  … ещё {len(doc['findings']) - 12} находок(и) того же вида "
                     "(полный перечень — `--json`)")
    parity = doc.get("parity_with_census")
    if parity is None:
        lines.append("  [НЕ ИЗМЕРЕНО] паритет с населением соседа не спрошен")
    elif parity["state"] == "unmeasured":
        lines.append(f"  [НЕ ИЗМЕРЕНО] паритет с соседом: {parity['why']}")
    elif parity["state"] == "equal":
        lines.append(f"  паритет с населением соседа: РАВНО "
                     f"({parity['census_pairs']} пар(ы), счёт независимый) ⇒ дорога "
                     "добавлена К правилу, а не вместо него")
    else:
        lines.append(f"  [ПАРИТЕТ РАСХОДИТСЯ] только здесь {parity['n_only_here']} · "
                     f"только у соседа {parity['n_only_in_census']}: "
                     + " · ".join(parity["only_here"] + parity["only_in_census"]))
    if doc.get("tests_outside_the_graph"):
        lines.append(f"  [НЕ ИЗМЕРЕНО] тест-файлов вне графа "
                     f"{len(doc['tests_outside_the_graph'])} (обход теста и обход "
                     "графа видят разные множества — перечень пропуска): "
                     + " · ".join(doc["tests_outside_the_graph"][:5]))
    if doc["unparsed_tests"]:
        lines.append(f"  [НЕ ИЗМЕРЕНО] тест-файлов не разобрано {len(doc['unparsed_tests'])}: "
                     + " · ".join(doc["unparsed_tests"][:5]))
    lines.append(f"  НИЖНЯЯ ГРАНИЦА: {counts[VIA_HELPER]} есть нижняя граница, и у неё три "
                 f"названные цены — дорога длиннее предела {counts[BEYOND]} · "
                 f"имя вне дерева {names.get(NAME_OUTSIDE, 0)} (дуга не пройдена) · "
                 f"имя не разрешено {names.get(NAME_UNRESOLVED, 0)}"
                 + (f" (например: {', '.join(doc['unresolved_examples'][:3])})"
                    if doc["unresolved_examples"] else ""))
    lines.append("  НЕ ДОКЛАДЫВАЕТ: ТРОГАЕТ ли тест поверхность на самом деле (дорога "
                 "импорта есть достижимость, а не исполнение) · имя, вычисляемое в "
                 "рантайме · дугу через сторонний модуль · верность самого перечня "
                 "поверхностей (он объявлен соседом)")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Односторонность правила принадлежности §49 — измерена "
                    "транзитивным замыканием импортов (заказ G87 п. 2)")
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument("--max-depth", type=int, default=MAX_DEPTH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    doc = measure(args.root, max_depth=args.max_depth)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(doc))
    return {"unmeasured": 2, "rule_is_one_sided": 1,
            "no_helper_reach_found": 0}[verdict(doc)]


if __name__ == "__main__":
    sys.exit(main())
