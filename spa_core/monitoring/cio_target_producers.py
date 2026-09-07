"""cio_target_producers.py — КТО ЕЩЁ производит цель, кроме нашего аллокатора,
и на какой поверхности у КАЖДОГО производителя стоя́т три ограничения владельца.

Почему этот замер вообще понадобился
====================================
ADR-250 (§41 ТЗ «Portfolio CIO», цикл #510) измерил, что три ограничения
владельца связывают ТОЛЬКО у аллокатора и молчат у гейта ``_apply_risk_policy_gate``:

======================================  ==========================================
ограничение                             у гейта
======================================  ==========================================
суммарный потолок тира (T3 ≤ 15 %)      не применяется: T3 25 % проходит с нулём
                                        нарушений
незнакомый тир                          не отвергается — МОЛЧА получает потолок T2
сеть (SINGLE/L2/BASE_CHAIN_CAP)         не судится ВОВСЕ
======================================  ==========================================

И сделал вывод дословно: «эти три ограничения держатся тем, что цель приходит от
НАШЕГО аллокатора; цель из любого другого источника последней двери по ним не
встретит».

**Этот вывод НЕ был измерен, а от него зависит, находка это или теория.** Если
единственный производитель цели — ``StrategyAllocator``, разрыв теоретический и
стоит строки в ADR. Если целей производят несколько, то у части книги три
ограничения не стои́т НИ НА ОДНОЙ поверхности — и это находка другого веса.
Модуль отвечает на это ЗАМЕРОМ, а не списком из головы.

Что здесь называется «производителем цели»
==========================================
Контракт ОБЪЯВЛЕН, а не выведен: **производитель цели — код, который РЕШАЕТ,
какие именованные позиции держать.** Советующий модуль, чей ответ никто не
держит (рейтинг, отчёт, дашборд), — не производитель, сколько бы он ни звался
``optimize``/``allocate``. Разбор дерева по ИМЕНИ вызова этой границы не видит:
в дереве 23 вызова ``optimize`` и 18 ``allocate``, и подавляющее большинство из
них — советники.

**Решать и записывать — РАЗНЫЕ роли, и требовать обе от каждого нельзя.** Замер
07.09: ``data/current_positions.json`` пишет ТОЛЬКО ``portfolio_rebalancer``, а
``StrategyAllocator`` — главный производитель цели в системе — не пишет ничего,
он предлагает веса. Проба «у производителя есть сайт записи» объявила бы его
пропавшим.

Поэтому объявленный список ПРОВЕРЯЕТСЯ разбором дерева с двух сторон
(:func:`_enumerate_producers`):

1. у каждого объявленного производителя должен найтись либо сайт записи книги,
   либо вызов, решающий её состав — иначе объявление устарело (``UNCHECKED``,
   громко);
2. ни один НЕобъявленный сайт записи книги не должен РЕШАТЬ её состав — а если
   решает, он выдаётся находкой ``undeclared_book``. Именно этот второй проход
   и отвечает на вопрос «кто ЕЩЁ», потому что он находит то, чего в списке нет.

🪤 Две ловушки, ради которых модуль устроен так, а не проще
==========================================================
**Первая: «ограничение есть в дереве» ≠ «ограничение стои́т на пути решения».**
``spa_core/execution/router.py`` несёт ``allowed_chains`` и
``blacklisted_protocols``, но read-only путь его НЕ импортирует по инварианту 6.
Замер, нашедший имя грепом, объявил бы ограничение существующим — верный ответ на
не тот вопрос. Поэтому здесь НИЧЕГО не решает греп: каждое ограничение меряется
ПОВЕДЕНЧЕСКИ — производителю подаётся нарушающая цель, и смотрится, что он с ней
сделал.

**Вторая, тише и потому опаснее: «производитель принял нарушающую цель» и
«нарушающая цель до него не доходит» — РАЗНЫЕ ответы, а выглядят одинаково.**
Книга рукава набирается из ``data/apy_ranking.json``; если бы в этой вселенной не
было ни одного T3-имени, «потолок T3 не связывает» было бы правдой без
последствий. Поэтому у молчания ДВА исхода, и какой из них верен, решает
отдельное измерение вселенной (:func:`_reachable_names`), а не рассуждение.

Четыре исхода на пару (производитель × ограничение)
===================================================
``BINDING``
    нарушающая цель отвергнута или срезана собственным допуском производителя.
``SILENT``
    нарушающая цель принята как есть, И нарушающие имена в его вселенной ЕСТЬ —
    то есть ограничение отсутствует на достижимом пути.
``UNREACHABLE``
    нарушающая цель принята, но ни одного нарушающего имени в его вселенной нет.
    Ограничения нет, последствий сегодня нет; завтрашнее пополнение вселенной
    делает это ``SILENT`` без единой правки кода.
``UNCHECKED``
    измерить не удалось, причина названа. Не ноль, не скип, не «прошло».

Положительный контроль — условие ВСЕГО отчёта
=============================================
«Ограничение не сработало» ничего не значит, если проба сломана. Счёт читается,
только если выполнены ОБА условия:

1. **здоровую цель принимает КАЖДЫЙ производитель** — иначе перехода
   «принято → отвергнуто» показать нечем, и всякое «отвергнуто» ниже
   неотличимо от производителя, который отвергает вообще всё;
2. **нарушающая сцена действительно нарушает** — доля T3 в ней считается
   НЕЗАВИСИМО от производителя и сверяется с объявленным порогом. Без этого
   «принял нарушающую цель» произносилось бы и над целью, которая ничего не
   нарушает; ровно так проба и зеленеет молча.

Не выполнено — ``control.passed = False``, ``overall = UNCHECKED``, счёт по
производителям читать нельзя.

Что НЕ утверждается этим модулем
================================
* Не утверждается, что книга рукава — живой трек. Рукава B/C держат СВОИ
  виртуальные $100k каждый (``PACKAGE_SEED_USD``) и по CLAUDE.md капитал
  основного трека не двигают. Утверждается ровно измеренное: это книги,
  которые система держит и публикует как пакеты Balanced и Aggressive, и три
  названных владельцем ограничения на них не стоя́т.
* Не утверждается покрытие ветвей: модуль судит о ФУНКЦИЯХ пути решения, а не о
  том, доходит ли до каждой живой цикл в каждом случае.
* Не переоткрывается уже записанное. Тождество пулов
  (``data/pool_identity_collision.json``) и потолки §41 (ADR-250) здесь не
  «находятся» второй раз.

ADVISORY. Ни один порог не меняется и ни одно недостающее ограничение не
строится: достроить ограничение — money-path и решение владельца, а не строка
замера.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
from typing import Any, Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_target_producers.json"

BINDING = "BINDING"
SILENT = "SILENT"
UNREACHABLE = "UNREACHABLE"
UNCHECKED = "UNCHECKED"

_SCENE_CAPITAL_USD = 100_000.0

# ── Три ограничения владельца, дословно из §41 ТЗ (порядок и формулировки его) ──
#   key, формулировка владельца, объявленный порог (для контроля сцены)
CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    ("t3_total", "allowed tiers — суммарный потолок тира",
     "RiskConfig.max_total_t3_allocation = 15 % (ADR-020)"),
    ("unknown_tier", "allowed tiers — незнакомый тир",
     "тир вне {T1,T2,T3} обязан быть отвергнут, а не получить потолок по умолчанию"),
    ("chain", "allowed chains — сетевые потолки",
     "SINGLE_CHAIN_CAP / L2_TOTAL_CAP / BASE_CHAIN_CAP = 20 % на Base (ADR-025/136)"),
)

# ── Объявленные книги: артефакт состояния ↔ производитель ──────────────────────
# Объявление, а не вывод (см. модульную строку). Второй проход разбора дерева
# ищет НЕобъявленные сайты записи книг — именно он отвечает «кто ЕЩЁ».
DECLARED_BOOKS: tuple[tuple[str, str, str], ...] = (
    ("data/current_positions.json", "spa_core/allocator/allocator.py",
     "канонический paper-трек: StrategyAllocator предлагает веса, цикл их держит"),
    ("data/current_positions.json", "spa_core/tuner/portfolio_rebalancer.py",
     "ALLOC-001: AllocationTuner + policy_enforcer, финальный писатель того же файла"),
    ("data/hy_paper_trading.json", "spa_core/paper_trading/hy_cycle.py",
     "книга рукава B (пакет Balanced), позиции строит sleeve_book.rebalance_book"),
    ("data/lp_paper_trading.json", "spa_core/paper_trading/lp_cycle.py",
     "книга рукава C (пакет Aggressive), позиции строит sleeve_book.rebalance_book"),
)

# Разбор дерева не заглядывает в тесты, в измерители (включая этот модуль) и в
# песочницы: их записи — сцены, а не книги системы.
#
# ⚠️ Вложенные рабочие деревья (``.claude/worktrees/``, ``/tmp``-копии) исключены
# ЯВНО. Без этого один и тот же сайт считается столько раз, сколько на машине
# сегодня лежит копий репозитория: замер 07.09 давал 60 «находок» из 5 реальных,
# и число менялось от уборки деревьев, а не от кода.
_SCAN_SKIP_PREFIXES = (
    ".git/", "tests/", "spa_core/tests/", "scripts/tests/", "research/",
    "docs/", "archive/", "landing/", "spa_core/monitoring/cio_",
    ".claude/", "node_modules/", "nimbalyst-local/",
)


# ─────────────────────────── разбор дерева ────────────────────────────────────

def _iter_runtime_modules(root: str):
    """Файлы рантайма, по которым идёт разбор. Тесты и измерители исключены."""
    import pathlib
    base = pathlib.Path(root)
    for path in sorted(base.rglob("*.py")):
        rel = path.relative_to(base).as_posix()
        if rel.startswith(_SCAN_SKIP_PREFIXES):
            continue
        if "/tests/" in rel or "/test_" in rel or rel.startswith("test_"):
            continue
        yield rel, path


# ── достижимость сайта от точек входа флота ───────────────────────────────────
#
# Зачем отдельная проба. Происхождение нагрузки (`DECIDES`/`DESCRIBES`) меряется
# по вызовам ВНУТРИ выражения, и на четырёх сайтах оно не установилось:
# `_sample_positions` (демо-CLI), пустой список вызовов (литерал в теле),
# `items` (сериализация собственного состояния), `compute_nav` (доказательство
# NAV из уже посчитанной книги). Замер 07.09 назвал их вслух третьим исходом —
# и это правильно, но перепись оставалась частичной, а от её полноты зависит
# ответ на вопрос заказа «кто ЕЩЁ».
#
# Второй вопрос закрывает разрыв, НЕ угадывая происхождение: **исполняется ли
# этот код в живой системе вообще.** Модуль, которого не запускает ни одна точка
# входа флота и который не импортирует (транзитивно) ни один нетестовый модуль,
# производителем цели не является — какой бы формы нагрузку он ни писал.
#
# 🪤 Ловушка, ради которой здесь третий исход. Ответ «недостижим» ЗАКРЫВАЕТ
# находку, поэтому проба, сломавшаяся молча, объявила бы недостижимым ВСЁ — то
# есть изготовила бы тишину. Поэтому: (1) не разобралась ни одна точка входа ⇒
# достижимость НЕ ИЗМЕРЕНА и сайты остаются `UNKNOWN`, громко; (2) обязателен
# положительный контроль — объявленные производители, про которых мы знаем, что
# они живые, ОБЯЗАНЫ попасть в достижимые; не попали ⇒ проба неисправна, и её
# вердикт не применяется вовсе.
_OFFLINE = "OFFLINE"


def _module_dotted(rel: str) -> str:
    """`spa_core/a/b.py` → `spa_core.a.b`."""
    return rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", ".")


def _fleet_entry_modules(root: str) -> set[str]:
    """Модули, которые ЗАПУСКАЮТ обёртки флота (`scripts/agent_*.sh`).

    Читается то, что обёртка передаёт запускателю, а не список из головы:
    launchd зовёт обёртку, обёртка называет цель. Форма `spa_core.<путь>` —
    модульная цель `python3 -m`.
    """
    import pathlib
    out: set[str] = set()
    for sh in sorted((pathlib.Path(root) / "scripts").glob("agent_*.sh")):
        try:
            text = sh.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.findall(r"spa_core\.[A-Za-z_0-9.]+", text):
            out.add(m.rstrip("."))
        # Обёртка бывает ДВУХ форм, и вторую первая редакция пробы не читала:
        # цель-СКРИПТ (`scripts/foo.py`). Положительный контроль поймал это
        # сразу — без скриптовых корней недостижимыми оказывались `allocator` и
        # `portfolio_rebalancer`, то есть ГЛАВНЫЕ производители цели: дневной
        # цикл заходит в них через скрипт, а не через `python3 -m`.
        for sc in re.findall(r"scripts/([A-Za-z_0-9]+)\.py", text):
            out.add(f"scripts.{sc}")
    return {m for m in out if m != "spa_core"}


def _import_graph(root: str) -> dict[str, set[str]]:
    """Кто кого импортирует, по РАЗБОРУ ДЕРЕВА (тесты исключены тем же фильтром)."""
    graph: dict[str, set[str]] = {}
    for rel, path in _iter_runtime_modules(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        deps: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                deps.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                deps.add(n.module)
                deps.update(f"{n.module}.{a.name}" for a in n.names)
        graph[_module_dotted(rel)] = deps
    return graph


def _live_reachable(root: str) -> tuple[set[str] | None, str]:
    """Модули, достижимые от точек входа флота. `None` ⇒ НЕ ИЗМЕРЕНО (с причиной).

    Достижимость считается по импортам от каждой точки входа обёрток. Сам факт
    «модуль есть в дереве» достижимостью не является — именно на этом ловится
    демо-CLI, который никто не запускает.
    """
    entries = _fleet_entry_modules(root)
    if not entries:
        return None, ("ни одна обёртка флота не разобрана — достижимость "
                      "мерить нечем")
    graph = _import_graph(root)
    if not graph:
        return None, "ни один модуль рантайма не разобран"
    known = set(graph)
    reach: set[str] = set()
    stack = [e for e in entries]
    while stack:
        cur = stack.pop()
        if cur in reach:
            continue
        reach.add(cur)
        for dep in graph.get(cur, ()):
            # Импорт `from pkg.mod import name` даёт и `pkg.mod.name`; в графе
            # живёт только модуль, поэтому берётся самый длинный известный префикс.
            cand = dep
            while cand and cand not in known:
                cand = cand.rpartition(".")[0]
            if cand and cand not in reach:
                stack.append(cand)
    return reach, ""


def _string_constants(tree: ast.AST) -> set[str]:
    """Все строковые литералы модуля — материал для резолва имени артефакта."""
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


# Имена, вызов которых означает, что модуль САМ решает состав книги, и имена,
# вызов которых означает, что он лишь читает уже принятое решение. Списки
# объявлены; неопознанное происхождение даёт третий исход, а не догадку.
_DECIDERS = ("optimize", "rebalance_book", "rebalance_portfolio", "allocate",
             "_enforce_t3_total_cap", "_enforce_chain_caps", "validate_positions")
_LOADERS = ("_load_portfolio_state", "atomic_load", "load_state", "_load_state",
            "read_text", "load", "_read_json")


def _assignments(fn: ast.AST) -> dict[str, ast.AST]:
    """Имя → выражение, которым оно связано, в пределах функции.

    Распаковка кортежа связывает КАЖДОЕ имя со всем правым выражением. Без этого
    ветка молчала бы ровно на той форме, которой пользуется живой код:
    ``book, opened, closed = sleeve_book.rebalance_book(...)`` в ``hy_cycle`` —
    то есть проба не видела бы происхождения книги у настоящего производителя
    и объявляла бы его ``UNKNOWN``.
    """
    out: dict[str, ast.AST] = {}

    def _bind(target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Name):
            out[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                _bind(elt, value)

    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                _bind(tgt, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            _bind(node.target, node.value)
    return out


def _resolve(node: ast.AST | None, binds: dict[str, ast.AST],
             depth: int = 0) -> ast.AST | None:
    """Развернуть имя до его выражения — до неподвижной точки, как в ADR-247."""
    while isinstance(node, ast.Name) and node.id in binds and depth < 12:
        node = binds[node.id]
        depth += 1
    return node


def _called_names(node: ast.AST | None, binds: dict[str, ast.AST],
                  depth: int = 0) -> set[str]:
    """Имена всех вызовов, из которых ПРОИСХОДИТ значение узла."""
    node = _resolve(node, binds, depth)
    if node is None or depth > 12:
        return set()
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            nm = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else None)
            if nm:
                names.add(nm)
            for arg in sub.args:
                names |= _called_names(arg, binds, depth + 1)
        elif isinstance(sub, ast.Name) and sub.id in binds and sub is not node:
            names |= _called_names(sub, binds, depth + 1)
    return names


def _book_shaped_writes(rel: str, tree: ast.AST,
                        literals: set[str]) -> list[dict]:
    """Сайты записи, чья нагрузка имеет ФОРМУ книги, с приговором о происхождении.

    Форма книги объявлена явно: словарь, среди ключей которого есть
    ``positions`` или ``book``. Признак СТРУКТУРНЫЙ, а не по имени файла —
    иначе новый производитель с новым именем артефакта не нашёлся бы вовсе, а
    найти его и есть цель прохода. Нагрузка-переменная разворачивается до своего
    литерала (``_resolve``): без этого проход не видел бы ни одного настоящего
    писателя, зато исправно находил бы тех, кто пишет словарь прямо в вызове.

    🪤 **Форма книги ≠ решение о книге, и первая редакция этого прохода на том и
    поймалась.** ``export_data.py`` пишет ``drift_report.json`` с ключом
    ``positions`` — и был объявлен пятым производителем цели. А он НЕ решает,
    что держать: его ``positions`` происходят из ``_load_portfolio_state()``,
    то есть из уже принятого кем-то решения. Ложная находка такого рода не
    краснеет никогда — она выглядит как успех проверки. Поэтому у каждого
    найденного сайта меряется ПРОИСХОЖДЕНИЕ нагрузки:

    ``DECIDES``   значение происходит из вызова, который решает состав книги;
    ``DESCRIBES`` значение происходит только из загрузки уже принятого;
    ``UNKNOWN``   ни то, ни другое установить не удалось — третий исход, и он
                  делает перепись частичной ВСЛУХ, а не выдаёт себя за находку.
    """
    out: list[dict] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            continue
        binds = _assignments(fn)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if name not in ("atomic_save", "write_text", "dump", "dumps"):
                continue
            payload = _resolve(node.args[0] if node.args else None, binds)
            if not isinstance(payload, ast.Dict):
                continue
            keys = {k.value for k in payload.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            hit = keys & {"positions", "book"}
            if not hit:
                continue
            value = next(v for k, v in zip(payload.keys, payload.values)
                         if isinstance(k, ast.Constant) and k.value in hit)
            origin_calls = _called_names(value, binds)
            if origin_calls & set(_DECIDERS):
                provenance, why = "DECIDES", sorted(origin_calls & set(_DECIDERS))
            elif origin_calls & set(_LOADERS):
                provenance, why = "DESCRIBES", sorted(origin_calls & set(_LOADERS))
            else:
                provenance, why = "UNKNOWN", sorted(origin_calls)[:6]
            targets = sorted(s for s in literals if s.endswith(".json"))
            out.append({"module": rel, "line": node.lineno,
                        "writer": name, "keys": sorted(keys),
                        "provenance": provenance, "origin": why,
                        "artifact_candidates": targets,
                        "resolved": bool(targets)})
    # Один и тот же сайт может встретиться из вложенных областей — дедуп по строке.
    seen: set[int] = set()
    uniq = []
    for w in out:
        if w["line"] in seen:
            continue
        seen.add(w["line"])
        uniq.append(w)
    return uniq


def _enumerate_producers(root: str) -> dict:
    """Перепись производителей цели РАЗБОРОМ ДЕРЕВА, в обе стороны.

    Возвращает ``{"declared": [...], "undeclared": [...], "unresolved": [...],
    "parse_failures": [...], "complete": bool, "reason": str}``.
    """
    declared_modules = {mod for _, mod, _ in DECLARED_BOOKS}

    # Достижимость — ВТОРОЙ вопрос к неразрешённому сайту (см. блок выше).
    # Положительный контроль обязателен: объявленные производители заведомо
    # живые, и если проба их не видит — она неисправна, и её вердикт не
    # применяется ВОВСЕ (иначе «недостижим» стало бы механизмом тишины).
    reachable, reach_unmeasured = _live_reachable(root)
    if reachable is not None:
        blind = sorted(_module_dotted(m) for m in declared_modules
                       if _module_dotted(m) not in reachable)
        if blind:
            reachable, reach_unmeasured = None, (
                "положительный контроль достижимости не пройден: объявленные "
                "производители не видны пробе (" + ", ".join(blind[:4]) + ") — "
                "вердикт «недостижим» не применяется")

    seen_writes: dict[str, list[dict]] = {}
    undeclared: list[dict] = []
    unresolved: list[dict] = []
    parse_failures: list[dict] = []

    for rel, path in _iter_runtime_modules(root):
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            parse_failures.append({"module": rel, "error":
                                   f"{type(exc).__name__}: {exc}"})
            continue
        writes = _book_shaped_writes(rel, tree, _string_constants(tree))
        if not writes:
            continue
        seen_writes[rel] = writes
        for w in writes:
            if not w["resolved"]:
                unresolved.append(w)
            if rel in declared_modules:
                continue
            # НЕобъявленный сайт становится находкой только если он РЕШАЕТ состав
            # книги. Описывающий (drift-отчёт, дашборд, экспорт) производителем
            # цели не является, и объявлять его им значило бы изготовить находку.
            if w["provenance"] == "DECIDES":
                undeclared.append(w)
            elif w["provenance"] == "UNKNOWN":
                if (reachable is not None
                        and _module_dotted(rel) not in reachable):
                    # Происхождение нагрузки так и не установлено — но код,
                    # которого не исполняет никто, цель не производит. Это
                    # ИЗМЕРЕНИЕ, а не смягчение: станет достижимым — снова
                    # станет громким.
                    # `resolved` НЕ трогается: он отвечает на другой вопрос —
                    # удалось ли назвать артефакт, — и подмена одного ответа
                    # другим и есть та ошибка, которую этот модуль ловит.
                    w["provenance"] = _OFFLINE
                    w["origin"] = ["не достижим ни от одной точки входа флота"]
                else:
                    unresolved.append(w)

    # Обратная сторона: объявленный производитель, у которого не нашлось НИ
    # сайта записи книги, НИ вызова, решающего её состав. Это не «всё хорошо» —
    # это устаревшее объявление.
    #
    # Роли РАЗНЫЕ, и мерить их одной пробой было бы ошибкой: замер 07.09 —
    # ``current_positions.json`` пишет ТОЛЬКО ``portfolio_rebalancer``;
    # ``StrategyAllocator`` книгу не пишет вовсе, он предлагает веса, а книгу
    # ведёт ребалансер. Требование «у каждого объявленного есть сайт ЗАПИСИ»
    # объявило бы аллокатор — самого производителя цели в системе — пропавшим.
    missing = []
    for artifact, module, why in DECLARED_BOOKS:
        if module in seen_writes:
            continue
        path = os.path.join(root, module)
        try:
            tree = ast.parse(open(path, "r", encoding="utf-8").read())
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            missing.append({"module": module, "artifact": artifact, "why": why,
                            "checked": f"не разобран: {type(exc).__name__}: {exc}"})
            continue
        decides = sorted({
            (n.func.attr if isinstance(n.func, ast.Attribute) else
             getattr(n.func, "id", "")) for n in ast.walk(tree)
            if isinstance(n, ast.Call)} & set(_DECIDERS))
        if decides:
            seen_writes.setdefault(module, []).append(
                {"module": module, "line": 0, "writer": "—",
                 "keys": [], "provenance": "DECIDES", "origin": decides,
                 "artifact_candidates": [artifact], "resolved": True,
                 "role": "решает состав книги, записывает её другой модуль"})
            continue
        missing.append({"module": module, "artifact": artifact, "why": why,
                        "checked": "ни сайта записи книги, ни вызова, решающего "
                                   "её состав, в модуле не найдено"})

    complete = not parse_failures and not unresolved and not missing
    reason = ""
    if parse_failures:
        reason = (f"{len(parse_failures)} модул(ь/я/ей) не разобрались "
                  f"({parse_failures[0]['module']}: {parse_failures[0]['error']})")
    elif unresolved:
        unnamed = [w for w in unresolved if not w["resolved"]]
        unknown = [w for w in unresolved if w.get("provenance") == "UNKNOWN"]
        parts = []
        if unknown:
            parts.append(
                f"{len(unknown)} сайт(ов) пишут нагрузку формы книги, но "
                f"происхождение их позиций не установлено (решают состав или "
                f"описывают уже принятое — не измерено): "
                + ", ".join(f"{w['module']}:{w['line']}" for w in unknown[:6]))
        if unnamed:
            parts.append(f"{len(unnamed)} сайт(ов) без резолва имени артефакта")
        reason = "; ".join(parts) + " — перепись частичная"
    elif missing:
        reason = ("у объявленн(ого/ых) производител(я/ей) не найден сайт записи "
                  "книги: " + ", ".join(m["module"] for m in missing)
                  + " — объявление устарело либо разбор его не видит")
    return {"declared": [{"artifact": a, "module": m, "why": w}
                         for a, m, w in DECLARED_BOOKS],
            "declared_writes_found": {k: v for k, v in seen_writes.items()
                                      if k in declared_modules},
            "undeclared": undeclared, "unresolved": unresolved,
            "missing_declared": missing, "parse_failures": parse_failures,
            "complete": complete, "reason": reason}


# ─────────────────────── вселенная имён (достижимость) ────────────────────────

def _t3_populations() -> dict[str, set[str]]:
    """Кого КАЖДАЯ поверхность считает T3. Множества РАЗНЫЕ, и это измерено.

    ``policy_enforcer`` судит по собственному набору ``T3_ADAPTERS``, аллокатор —
    по каноническому ``tier_map.tier_of`` (ADR-020). Замер 07.09: наборы
    расходятся на три имени, и «T3 ≤ 15 %» на двух поверхностях означает
    поэтому не совсем одно и то же. Для сцены берётся ПЕРЕСЕЧЕНИЕ — имя, которое
    T3 для обеих; иначе «принял» у одной поверхности значило бы лишь то, что она
    не считает это имя третьим тиром, а вовсе не отсутствие потолка.
    """
    from spa_core.risk.policy_enforcer import T3_ADAPTERS
    from spa_core.adapters.tier_map import tier_of
    from spa_core.adapters import ADAPTER_REGISTRY

    enforcer = set(T3_ADAPTERS)
    names = {n for n, *_ in ADAPTER_REGISTRY} | enforcer
    canonical = set()
    for n in names:
        try:
            if str(tier_of(n) or "").upper() == "T3":
                canonical.add(n)
        except Exception:  # noqa: BLE001
            continue
    return {"policy_enforcer": enforcer, "tier_map": canonical,
            "both": enforcer & canonical}


def _t3_names() -> set[str]:
    """Имена, которые T3 для ОБЕИХ поверхностей — материал нарушающей сцены."""
    return _t3_populations()["both"]


def _base_chain_names() -> set[str]:
    """Имена, чья сеть — Base. Резолвится ТЕМ ЖЕ кодом, что у гейта и аллокатора."""
    from spa_core.risk.policy_enforcer import _resolve_chain_map
    from spa_core.adapters import ADAPTER_REGISTRY
    names = [n for n, *_ in ADAPTER_REGISTRY] if ADAPTER_REGISTRY else []
    chain_map, _ = _resolve_chain_map(names)
    return {n for n, c in chain_map.items() if str(c).lower() == "base"}


def _reachable_names(root: str, producer: str) -> tuple[set[str], str]:
    """Вселенная имён, из которых производитель вообще может набрать книгу.

    Возвращает ``(имена, причина_если_не_измерено)``. Пустая вселенная при
    пустой причине означала бы «нарушить нечем», и это НЕ то же самое, что
    «не измерено» — поэтому причина возвращается отдельно, а не кодируется
    пустотой.
    """
    if producer in ("spa_core/paper_trading/hy_cycle.py",
                    "spa_core/paper_trading/lp_cycle.py"):
        path = os.path.join(root, "data", "apy_ranking.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                rows = json.load(fh).get("by_apy") or []
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return set(), (f"вселенная рукава не прочитана "
                           f"({type(exc).__name__}: {exc}) — «нарушить нечем» "
                           f"и «не измерено» неотличимы, и второе честнее")
        return {str(r.get("protocol") or "").strip() for r in rows
                if isinstance(r, dict) and r.get("protocol")}, ""
    # Аллокатор и ребалансер набирают из реестра адаптеров — константы кода.
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
        return {n for n, *_ in ADAPTER_REGISTRY}, ""
    except Exception as exc:  # noqa: BLE001
        return set(), f"ADAPTER_REGISTRY не прочитан: {type(exc).__name__}: {exc}"


# ───────────────────────── допуски производителей ─────────────────────────────
#
# У каждого производителя — СВОЙ допуск, и это принципиально: три ограничения
# ищутся не по имени функции, а по поведению того допуска, который стои́т именно
# на его пути.

def _allocator_admit(weights: dict[str, float]) -> dict[str, float]:
    """Допуск StrategyAllocator: оба ``_enforce_*`` подряд, как в ``allocate``."""
    from spa_core.allocator.allocator import StrategyAllocator
    alloc = StrategyAllocator.__new__(StrategyAllocator)
    capped, _ = StrategyAllocator._enforce_t3_total_cap(alloc, dict(weights))
    capped, _ = StrategyAllocator._enforce_chain_caps(alloc, capped)
    return {k: round(float(v), 6) for k, v in capped.items()}


def _enforcer_admit(weights: dict[str, float]) -> dict[str, float]:
    """Допуск portfolio_rebalancer: ``policy_enforcer.validate_positions``.

    Отказ здесь — fail-closed: книга НЕ пишется вовсе. Поэтому отвергнутая цель
    возвращается пустой книгой, а не срезанной: это и есть то, что делает
    производитель.
    """
    from spa_core.risk.policy_enforcer import validate_positions
    positions = {k: v * _SCENE_CAPITAL_USD for k, v in weights.items()}
    cash = _SCENE_CAPITAL_USD - sum(positions.values())
    res = validate_positions(positions, _SCENE_CAPITAL_USD, cash_usd=max(0.0, cash))
    if not res.passed:
        return {}
    return {k: round(float(v), 6) for k, v in weights.items()}


def _sleeve_admit(weights: dict[str, float]) -> dict[str, float]:
    """Допуск рукавов B/C: ``sleeve_book.rebalance_book`` над теми же именами.

    Кандидаты строятся из имён цели с APY внутри полосы рукава — иначе проба
    мерила бы полосу доходности, а не ограничения владельца.
    """
    from spa_core.paper_trading import sleeve_book
    cands = [{"protocol": name, "apy_pct": 8.0} for name in sorted(weights)]
    book, _, _ = sleeve_book.rebalance_book(
        [], sleeve_book.hy_candidates(cands), _SCENE_CAPITAL_USD,
        today="2026-01-01", max_positions=max(4, len(cands)))
    return {p["protocol"]: round(p["notional_usd"] / _SCENE_CAPITAL_USD, 6)
            for p in book}


def _gate_admit(weights: dict[str, float]) -> dict[str, float]:
    """Последняя дверь: ``_apply_risk_policy_gate``. Отказ ⇒ пустая книга."""
    import pathlib
    import tempfile
    from spa_core.adapters.tier_map import tier_of
    from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate

    def _tier(name: str) -> str:
        # Тир берётся у КАНОНИЧЕСКОГО резолвера, а не проставляется литералом:
        # литерал «T2» на всех именах сделал бы здоровую сцену нарушающей сама
        # по себе (T1-имена под T2-потолком), и контроль честно бы её завернул.
        try:
            return str(tier_of(name) or "").upper() or "T2"
        except Exception:  # noqa: BLE001
            return "T2"

    target = {k: v * _SCENE_CAPITAL_USD for k, v in weights.items()}
    spec = [{"protocol": name, "tier": _tier(name), "apy_pct": 8.0,
             "tvl_usd": 500_000_000.0, "tvl_source": "live"}
            for name in sorted(weights)]
    with tempfile.TemporaryDirectory() as ddir:
        res = _apply_risk_policy_gate(target, _SCENE_CAPITAL_USD, spec,
                                      ddir=pathlib.Path(ddir))
    approved = bool(res.get("approved")) if isinstance(res, dict) else bool(res)
    return {k: round(float(v), 6) for k, v in weights.items()} if approved else {}


PRODUCERS: tuple[tuple[str, str, Callable[[dict], dict]], ...] = (
    ("spa_core/allocator/allocator.py", "StrategyAllocator._enforce_*",
     _allocator_admit),
    ("spa_core/tuner/portfolio_rebalancer.py", "policy_enforcer.validate_positions",
     _enforcer_admit),
    ("spa_core/paper_trading/hy_cycle.py", "sleeve_book.rebalance_book",
     _sleeve_admit),
    ("spa_core/paper_trading/lp_cycle.py", "sleeve_book.rebalance_book",
     _sleeve_admit),
    ("spa_core/paper_trading/cycle_runner.py", "_apply_risk_policy_gate",
     _gate_admit),
)


# ─────────────────────────────── сцены ────────────────────────────────────────

def _scenes(root: str) -> dict[str, dict]:
    """Здоровая цель и три нарушающие. Строятся из ЖИВЫХ имён, а не выдуманных.

    Выдуманное имя ответило бы на вопрос «что делает система с несуществующим
    протоколом», а спрошено другое — что она делает с реальным.
    """
    t3 = sorted(_t3_names())
    base = sorted(_base_chain_names())
    healthy = {"aave_v3": 0.30, "compound_v3": 0.30, "pendle": 0.15}
    scenes: dict[str, dict] = {"healthy": {"weights": healthy, "violates": None}}

    if len(t3) >= 2:
        # 25 % на двух именах: 13 % + 12 %. Ни одно из них по отдельности не
        # упирается в потолок концентрации, поэтому срез, если он произойдёт,
        # произойдёт именно от СУММАРНОГО потолка тира, а не от per-protocol —
        # иначе проба мерила бы соседнее ограничение и называла его этим.
        scenes["t3_total"] = {
            "weights": {"aave_v3": 0.30, t3[0]: 0.13, t3[1]: 0.12},
            "violates": "доля T3 = 25.0 % при объявленном потолке 15.0 %",
            "names": t3[:2]}
    elif len(t3) == 1:
        scenes["t3_total"] = {
            "weights": {"aave_v3": 0.30, t3[0]: 0.25},
            "violates": "доля T3 = 25.0 % при объявленном потолке 15.0 %",
            "names": t3[:1]}
    else:
        scenes["t3_total"] = {"unchecked": (
            "ни одного имени, которое T3 для ОБЕИХ поверхностей — сцену на "
            "25 % не собрать так, чтобы её признали нарушающей обе")}

    scenes["unknown_tier"] = {
        "weights": {"aave_v3": 0.30, "compound_v3": 0.30,
                    "spa_unknown_tier_probe": 0.15},
        "violates": "имя с неопределимым тиром занимает 15 % книги",
        "names": ["spa_unknown_tier_probe"]}

    # Сетевая сцена собирается ТРЕМЯ именами по 15 %, а не двумя по 30 %, и ни
    # одно из них не считается T3 ни одной из поверхностей. Причина ровно та же,
    # что у сцены T3: 30 % на имя упирается в потолок КОНЦЕНТРАЦИИ (T2 = 20 %),
    # а T3-имя — в суммарный потолок тира. Первая редакция этой сцены давала
    # `BINDING` у гейта на сетевом ограничении — при том, что гейт сети не
    # судит ВОВСЕ (ADR-250): отвергал он её за концентрацию. Верный ответ на не
    # тот вопрос, и в отчёте он был бы неотличим от работающего потолка сети.
    t3_any = _t3_populations()
    base_clean = [n for n in base
                  if n not in t3_any["policy_enforcer"] and n not in t3_any["tier_map"]]
    if len(base_clean) >= 3:
        scenes["chain"] = {
            "weights": {base_clean[0]: 0.15, base_clean[1]: 0.15,
                        base_clean[2]: 0.15, "aave_v3": 0.15},
            "violates": "доля сети Base = 45.0 % при объявленном потолке 20.0 %",
            "names": base_clean[:3]}
    else:
        scenes["chain"] = {"unchecked": (
            f"Base-имён вне обоих T3-наборов {len(base_clean)} — сцену нельзя "
            f"собрать так, чтобы она нарушала ТОЛЬКО сетевой потолок")}
    return scenes


def _scene_really_violates(key: str, scene: dict, root: str) -> tuple[bool, str]:
    """Контроль сцены: нарушает ли она объявленный порог — СЧЁТОМ, не намерением.

    Без этого «производитель принял нарушающую цель» произносилось бы и над
    целью, которая ничего не нарушает.
    """
    w = scene.get("weights") or {}
    if key == "t3_total":
        share = sum(v for p, v in w.items() if p in _t3_names())
        return share > 0.15 + 1e-9, f"доля T3 в сцене {share:.1%} (порог 15 %)"
    if key == "chain":
        base = _base_chain_names()
        share = sum(v for p, v in w.items() if p in base)
        return share > 0.20 + 1e-9, f"доля Base в сцене {share:.1%} (порог 20 %)"
    if key == "unknown_tier":
        from spa_core.adapters.tier_map import tier_of
        probe = "spa_unknown_tier_probe"
        try:
            tier = tier_of(probe)
        except Exception:  # noqa: BLE001
            tier = None
        known = str(tier or "").upper() in ("T1", "T2", "T3")
        return (not known), (f"тир имени `{probe}` не определяется "
                             f"(tier_of → {tier!r})" if not known
                             else f"имя `{probe}` неожиданно известно как {tier}")
    return False, "неизвестное ограничение"


# ──────────────────────────────── замер ───────────────────────────────────────

def _classify(admitted: dict, scene: dict,
              universe: set[str], universe_reason: str) -> tuple[str, str]:
    """Исход пары (производитель × ограничение) по РЕЗУЛЬТАТУ допуска."""
    weights = scene["weights"]
    offending = set(scene.get("names") or [])
    if not admitted:
        return BINDING, "цель отвергнута целиком (книга не пишется)"
    trimmed = {p for p in offending
               if admitted.get(p, 0.0) + 1e-9 < weights.get(p, 0.0)}
    if trimmed:
        return BINDING, ("срезаны нарушающие имена: "
                         + ", ".join(f"{p} {weights[p]:.0%}→{admitted.get(p,0.0):.0%}"
                                     for p in sorted(trimmed)))
    dropped = offending - set(admitted)
    if dropped:
        return BINDING, "нарушающие имена не взяты в книгу: " + ", ".join(sorted(dropped))
    # Принято без изменений — остаётся вопрос достижимости.
    if universe_reason:
        return UNCHECKED, (f"цель принята без изменений, но вселенная "
                           f"производителя не измерена: {universe_reason}")
    reachable = offending & universe
    if not reachable:
        return UNREACHABLE, ("цель принята без изменений, но ни одного "
                             "нарушающего имени в его вселенной нет: "
                             + ", ".join(sorted(offending)))
    return SILENT, ("цель принята без изменений; нарушающие имена в его "
                    "вселенной ЕСТЬ: " + ", ".join(sorted(reachable)))


def _live_books(root: str) -> list[dict]:
    """Что КАЖДАЯ книга держит СЕГОДНЯ и какова в ней доля T3.

    Без этого замер отвечал бы «ограничение не стои́т» — утверждение о коде, из
    которого не следует, что оно уже нарушено. С ним видно, теория это или
    состояние: доля считается каноническим ``tier_of`` над живым файлом книги.
    Файл нечитаем ⇒ ``unchecked`` с причиной, а не ноль: «книга пуста» и «книгу
    не прочли» — разные ответы.
    """
    from spa_core.adapters.tier_map import tier_of
    out: list[dict] = []
    for artifact, module, _why in DECLARED_BOOKS:
        if artifact == "data/current_positions.json":
            continue  # у него два объявленных производителя — не дублировать книгу
        path = os.path.join(root, artifact)
        entry: dict[str, Any] = {"artifact": artifact, "producer": module}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            entry["unchecked"] = f"{type(exc).__name__}: {exc}"
            out.append(entry)
            continue
        equity = float(state.get("equity") or 0.0)
        positions = [p for p in (state.get("positions") or []) if isinstance(p, dict)]
        if equity <= 0:
            entry["unchecked"] = "equity ≤ 0 — доли не считаются"
            out.append(entry)
            continue
        t3 = 0.0
        rows = []
        for p in positions:
            name = str(p.get("protocol") or "")
            usd = float(p.get("notional_usd") or 0.0)
            try:
                tier = str(tier_of(name) or "").upper() or None
            except Exception:  # noqa: BLE001
                tier = None
            if tier == "T3":
                t3 += usd
            rows.append({"protocol": name, "usd": round(usd, 2),
                         "share": round(usd / equity, 4), "tier": tier})
        entry.update({"equity": round(equity, 2), "positions": rows,
                      "t3_share": round(t3 / equity, 4),
                      "t3_declared_cap": 0.15,
                      "over_declared_cap": (t3 / equity) > 0.15 + 1e-9})
        out.append(entry)
    return out


def run(root: str = REPO_ROOT, *, write: bool = True,
        now: dt.datetime | None = None) -> dict:
    """Замер «кто ещё производит цель». Живой ``data/`` не пишется (кроме отчёта).

    ``data/apy_ranking.json`` ЧИТАЕТСЯ — это вселенная рукава, и подменить её
    литералом значило бы ответить на вопрос о выдуманной системе.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    enumeration = _enumerate_producers(root)

    control_reason = ""
    scenes: dict[str, dict] = {}
    try:
        scenes = _scenes(root)
    except Exception as exc:  # noqa: BLE001
        control_reason = f"сцены не построены: {type(exc).__name__}: {exc}"

    # Контроль 1: здоровую цель принимает КАЖДЫЙ производитель.
    healthy_verdicts: dict[str, str] = {}
    if not control_reason:
        for module, surface, admit in PRODUCERS:
            try:
                out = admit(scenes["healthy"]["weights"])
            except Exception as exc:  # noqa: BLE001
                control_reason = (f"{module}: здоровая цель не прошла пробу "
                                  f"({type(exc).__name__}: {exc})")
                break
            healthy_verdicts[module] = json.dumps(
                {k: round(v, 6) for k, v in sorted(out.items())}, ensure_ascii=False)
            if not out:
                control_reason = (
                    f"{module} ({surface}) отвергает ЗДОРОВУЮ цель — перехода "
                    f"«принято → отвергнуто» показать нечем, и всякое "
                    f"«отвергнуто» ниже неотличимо от производителя, который "
                    f"отвергает всё")
                break

    # Контроль 2: нарушающая сцена действительно нарушает.
    scene_control: dict[str, str] = {}
    if not control_reason:
        for key, wording, threshold in CONSTRAINTS:
            scene = scenes.get(key) or {}
            if "unchecked" in scene:
                scene_control[key] = f"НЕ ИЗМЕРЕНО: {scene['unchecked']}"
                continue
            ok, detail = _scene_really_violates(key, scene, root)
            scene_control[key] = detail
            if not ok:
                control_reason = (
                    f"сцена ограничения «{wording}» объявленный порог НЕ "
                    f"нарушает ({detail}) — «принял нарушающую цель» было бы "
                    f"сказано над целью, которая ничего не нарушает")
                break

    control_ok = not control_reason

    results: list[dict] = []
    for module, surface, admit in PRODUCERS:
        universe, universe_reason = ((set(), "контроль не пройден") if not control_ok
                                     else _reachable_names(root, module))
        for key, wording, threshold in CONSTRAINTS:
            entry: dict[str, Any] = {
                "producer": module, "admission_surface": surface,
                "constraint": key, "owner_wording": wording,
                "declared_threshold": threshold,
            }
            scene = scenes.get(key) or {}
            if not control_ok:
                entry.update({"outcome": UNCHECKED, "detail": "",
                              "unchecked_reason": control_reason})
                results.append(entry)
                continue
            if "unchecked" in scene:
                entry.update({"outcome": UNCHECKED, "detail": "",
                              "unchecked_reason": scene["unchecked"]})
                results.append(entry)
                continue
            try:
                admitted = admit(scene["weights"])
            except Exception as exc:  # noqa: BLE001 — упавшая проба это UNCHECKED
                entry.update({"outcome": UNCHECKED, "detail": "",
                              "unchecked_reason": f"{type(exc).__name__}: {exc}"})
                results.append(entry)
                continue
            outcome, detail = _classify(admitted, scene, universe,
                                        universe_reason)
            entry.update({"outcome": outcome, "detail": detail,
                          "unchecked_reason": "",
                          "scene": {k: round(v, 6)
                                    for k, v in scene["weights"].items()},
                          "admitted": {k: round(v, 6)
                                       for k, v in admitted.items()}})
            results.append(entry)

    live_books = _live_books(root)
    findings, unchecked = _findings(results, enumeration, control_ok,
                                    control_reason, live_books)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unchecked": len(unchecked),
    }
    overall = (UNCHECKED if not control_ok else
               "CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else "OK")
    doc = {
        "schema": "cio_target_producers/v1",
        "generated_at": now.isoformat(),
        "question": ("§41 ТЗ Portfolio CIO, остаток ADR-250: КТО ЕЩЁ производит "
                     "цель, кроме StrategyAllocator, и стоя́т ли у него три "
                     "названных владельцем ограничения — суммарный потолок "
                     "тира, незнакомый тир, сеть"),
        "overall": overall,
        "counts": counts,
        "enumeration": enumeration,
        "control": {"passed": control_ok, "reason": control_reason,
                    "healthy_admitted_by": healthy_verdicts,
                    "scene_violates": scene_control},
        "producers": [{"module": m, "admission_surface": s} for m, s, _ in PRODUCERS],
        "live_books": live_books,
        "matrix": results,
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: ни один порог не меняется и ни одно недостающее "
                     "ограничение не строится — достроить ограничение это "
                     "money-path и решение владельца"),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _findings(results: list[dict], enumeration: dict, control_ok: bool,
              control_reason: str,
              live_books: list[dict]) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []

    if not control_ok:
        unchecked.append(f"положительный контроль не пройден — {control_reason}; "
                         "счёт по производителям читать нельзя")
        return findings, unchecked

    if not enumeration["complete"]:
        findings.append({
            "severity": "WARN", "code": "enumeration_partial",
            "message": ("перепись производителей ЧАСТИЧНА: "
                        + enumeration["reason"]
                        + " — ответ «кто ещё» полон настолько, насколько полна "
                          "перепись, и это сказано вслух, а не сглажено")})
        unchecked.append("перепись производителей: " + enumeration["reason"])

    for w in enumeration["undeclared"]:
        findings.append({
            "severity": "CRITICAL", "code": f"undeclared_book:{w['module']}",
            "message": (f"{w['module']}:{w['line']} пишет нагрузку формы книги "
                        f"(ключи {', '.join(w['keys'])}), а в списке "
                        f"производителей его нет — это и есть «кто ЕЩЁ», "
                        f"найденный разбором, а не памятью")})

    silent = [r for r in results if r["outcome"] == SILENT]
    by_producer: dict[str, list[dict]] = {}
    for r in silent:
        by_producer.setdefault(r["producer"], []).append(r)

    for module, rows in sorted(by_producer.items()):
        names = ", ".join(f"«{r['owner_wording']}»" for r in rows)
        severity = "CRITICAL" if len(rows) == len(CONSTRAINTS) else "WARN"
        findings.append({
            "severity": severity, "code": f"silent:{module}",
            "message": (
                f"{module} (допуск: {rows[0]['admission_surface']}) принимает "
                f"нарушающую цель по {len(rows)} из {len(CONSTRAINTS)} "
                f"ограничен(ию/иям) владельца: {names}. "
                + ("НИ ОДНО из трёх не стои́т на этом пути. " if severity == "CRITICAL" else "")
                + "Измерено: " + "; ".join(r["detail"] for r in rows))})

    for b in live_books:
        if b.get("unchecked"):
            unchecked.append(f"живая книга {b['artifact']}: {b['unchecked']}")
            continue
        if not b.get("over_declared_cap"):
            continue
        names = ", ".join(f"{r['protocol']} {r['share']:.0%} [{r['tier'] or '—'}]"
                          for r in b["positions"])
        findings.append({
            "severity": "CRITICAL", "code": f"live_book_over_cap:{b['artifact']}",
            "message": (
                f"разрыв НЕ теоретический: книга {b['artifact']} "
                f"(производитель {b['producer']}) держит СЕГОДНЯ "
                f"{b['t3_share']:.1%} в T3 при объявленном потолке "
                f"{b['t3_declared_cap']:.0%} — состав: {names}. Ни одна "
                f"поверхность этого производителя суммарный потолок тира не "
                f"применяет, поэтому нарушать нечего: правила там нет")})

    guarded = {r["producer"] for r in results if r["outcome"] == BINDING}
    unguarded = {r["producer"] for r in results} - guarded
    findings.append({
        "severity": "INFO", "code": "verdict_on_adr250_claim",
        "message": (
            f"утверждение ADR-250 «три ограничения держатся тем, что цель "
            f"приходит от НАШЕГО аллокатора» проверено замером: производителей "
            f"цели {len({r['producer'] for r in results})}, из них хотя бы одно "
            f"ограничение связывает у {len(guarded)}; ни одного — у "
            f"{len(unguarded)}"
            + (": " + ", ".join(sorted(unguarded)) if unguarded else ""))})

    for r in results:
        if r["outcome"] == UNREACHABLE:
            findings.append({
                "severity": "INFO", "code":
                f"unreachable:{r['producer']}:{r['constraint']}",
                "message": (f"{r['producer']}: ограничение «{r['owner_wording']}» "
                            f"не стои́т, но сегодня нарушить его нечем — "
                            f"{r['detail']}. Пополнение вселенной делает это "
                            f"SILENT без единой правки кода")})
        if r["outcome"] == UNCHECKED:
            unchecked.append(f"{r['producer']} × «{r['owner_wording']}»: "
                             f"{r['unchecked_reason']}")
    return findings, unchecked


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    c = doc["counts"]
    print(f"cio_target_producers: {doc['overall']} (critical={c['critical']} "
          f"warn={c['warn']} info={c['info']} unchecked={c['unchecked']})")
    if not doc["control"]["passed"]:
        print(f"  [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
              f"{doc['control']['reason']}")
        return 0
    for r in doc["matrix"]:
        print(f"  {r['outcome']:12s} {r['producer']} × {r['constraint']} — "
              f"{r['detail'] or r['unchecked_reason']}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
