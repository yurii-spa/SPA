"""cio_component_map.py — §46 ТЗ «Portfolio CIO»: у каких из ДЕСЯТИ названных
владельцем ступеней есть эквивалент в дереве, и НЕСЁТ ли цепь через него ход.

Вопрос владельца дословно
=========================
§46 «Минимальный proposed component map»:

    Opportunity Data → Portfolio State → Portfolio Optimizer → Target Allocation
    → Rebalance Evaluator → Risk Gate → Execution Planner → Execution Agent
    → Post-Trade Monitor → Reporting

    «После исследования адаптировать к существующей архитектуре. **Не создавать
    новые компоненты, если эквиваленты уже существуют.**»

Требование одно, а вопросов в нём ДВА, и отвечают они по-разному:

1. **есть ли эквивалент** — чтобы не построить второй такой же;
2. **несёт ли цепь ход через него** — потому что ступень, чей продукт никто не
   читает, эквивалентом называться может, а работу карты не делает.

Первый вопрос почти всегда отвечается «да» (дерево большое), и на нём легко
остановиться, отчитавшись «карта построена». Второй и есть предмет замера.

🪤 Ловушка заказа #514: импорт — самая дешёвая улика и самая лживая
==================================================================
Заказ назвал её прямо: **«модуль импортирует соседа» ≠ «исполняет его роль»**.
``cycle_runner`` импортирует ``rebalance_trigger``, и по графу импортов ступень
«Rebalance Evaluator» выглядит встроенной в цепь. Она в неё не встроена: её
вердикт пишется в файл ПОСЛЕ того, как решение принято, и следующая ступень
карты этот файл не читает.

Поэтому здесь ничего не решает ни импорт, ни имя модуля. И роль, и стык меряются
**продуктом**: кто его производит и кто его получает. Ловушка закреплена
обратным контролем К3 — сцена, где сосед импортирован и даже вызван, но продукт
не прочитан, обязана остаться НЕ связанной.

🪤 Вторая ловушка, найденная на СЕБЕ: у носителя ДВА рода
=========================================================
Первая редакция этого модуля умела видеть только файловый носитель и объявила
``Portfolio State → Portfolio Optimizer`` односторонним: аллокатор действительно
не читает ``current_positions.json``. Но книгу ему подаёт ``cycle_runner``
значением, в памяти — то есть носитель ЕСТЬ, просто другого рода. Находка была бы
ложной, и родилась бы она не из дерева, а из слепоты прибора.

Поэтому носителей ищется два, и отсутствие объявляется только когда нет ОБОИХ:

``artifact``
    producer имеет САЙТ ЗАПИСИ пути, следующая ступень — САЙТ ЧТЕНИЯ. Не
    упоминание, а сайт: строка обязана дойти до аргумента вызова записи/чтения.
``in_process``
    объявленный ОРКЕСТРАТОР (:data:`ORCHESTRATORS`) зовёт вход предыдущей
    ступени, связывает результат с именем, и это имя доходит до аргумента вызова
    следующей ступени. Это строго сильнее импорта — и ровно этим отличается от
    ловушки выше.

Строку почти никогда не кладут литералом в аргумент
===================================================
Имя файла сидит в модульной константе (``POSITIONS_FILENAME``), константа уезжает
в возврат помощника (``_out_path``), помощник — в значение по умолчанию параметра
(``path=_DEFAULT_OUT``), и только оттуда в ``atomic_save``. Первая редакция
резолвила литералы под узлом аргумента и потому назвала НЕ ИЗМЕРЕННЫМИ девять
ступеней из десяти — слепой прибор сообщал не о дереве, а о себе. Происхождение
значения ищется **до неподвижной точки** (:func:`_symbol_strings`) — та же
дисциплина, что у сторожа ``injected-clock`` в ``.claude/rules/deployment.md``.

**Контейнер происхождением НЕ является** — и это тоже найдено на себе. Пока
обход спускался внутрь словарей и списков, ЛЮБОЙ модуль, собирающий отчёт с
именем файла где-то в теле, объявлялся его писателем: этот самый модуль первым
делом «написал» ``risk_policy_blocks.json``, потому что имя лежит в его
таблице ступеней. Путь строится из констант, имён и склеек — но не из элемента
словаря; та же граница, что у сторожа `injected-clock` (авария 2026-08-04).

«Решать» и «записывать» — РАЗНЫЕ роли, и требовать обе нельзя
=============================================================
Урок ADR-251 применён к самому этому замеру. ``rebalance_trigger.py`` НЕ пишет
``data/rebalance_trigger.json`` — его пишет ``cycle_runner``, взяв возвращённое
значение. Проба «у ступени есть свой сайт записи» объявила бы ступень пропавшей —
ложная находка, а не находка. Поэтому роль засчитывается и через ПОСРЕДНИКА
(:func:`_written_via_proxy`).

Половина исполнения инертна ПО ПОСТРОЕНИЮ, и это не находка
===========================================================
``draft_prep`` — уровень A: черновик подписывает ЧЕЛОВЕК (``signed=False``,
``requires_human_signature=True``); ``router`` держит ``dry_run``; а
``cycle_runner`` не импортирует ``spa_core/execution/`` вовсе (инвариант #6).
Требовать машинный носитель от такого стыка — верный ответ на не тот вопрос
(класс #511). Род ступени объявлен, но **проверяется разбором**: контракт обязан
быть виден в самом модуле, иначе род — ``UNCHECKED``, а не «поверили на слово».

Исходы на стык
==============
``WIRED`` — следующая ступень читает файл-продукт предыдущей.
``WIRED_IN_PROCESS`` — оркестратор передаёт продукт значением.
``ONE_WAY`` — продукт читают, но НЕ следующая ступень; читателей называем
поимённо. Прочитан отчётностью или шагом 0-офис ≠ несёт ход.
``DEAD_END`` — продукт не получает никто, кроме производителя.
``BY_DESIGN_HUMAN`` — стык выходит из ступени, чей продукт по построению
отдаётся человеку; машинного носителя здесь быть не должно.
``UNCHECKED`` — измерить не удалось, причина названа. Не ноль, не скип.

Положительный контроль — условие ВСЕГО отчёта
=============================================
«Читателя нет» ничего не значит, если проба слепа. Счёт читается, только если
выполнены ПЯТЬ условий (:func:`positive_control`); не выполнено любое ⇒
``overall="UNCHECKED"``:

**К1** проба умеет сказать «связано» на сцене, где читатель есть.
**К2** проба умеет сказать «не связано» на сцене, где его нет.
**К3, обратный** — импорт и вызов соседа БЕЗ чтения продукта связью не считаются
(та самая ловушка заказа).
**К4** второй носитель умеет сказать «да»: оркестратор, передающий результат
значением, обязан быть опознан.
**К5, обратный** — оркестратор, который зовёт обе ступени, но НЕ передаёт
результат, носителем не является. Без К5 второй носитель выродился бы в
«оба имени встретились в одном файле».
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from spa_core.monitoring.cio_architecture_constraints import (
    _docstring_ids,  # докстрока — не сайт вызова; дисциплина ADR-252
)

REPORT_REL = "data/cio_component_map.json"

#: Вызовы, аргумент которых означает ЗАПИСЬ пути.
_WRITE_FUNCS = {"atomic_save", "_atomic_save", "_atomic_write_json",
                "_atomic_write", "atomic_write_json", "write_text",
                "write_json", "save_json"}

#: Вызовы, аргумент которых означает ЧТЕНИЕ пути.
_READ_FUNCS = {"open", "read_text", "_read_json", "read_json", "load_json",
               "_load_json", "read_bytes"}

#: Узлы-контейнеры: путь из их содержимого НЕ происходит (см. докстроку).
_CONTAINERS = (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.DictComp,
               ast.ListComp, ast.SetComp, ast.GeneratorExp)

#: Модули, которые ВЕДУТ цепь в одном процессе. Объявлены, а не выведены:
#: «оркестратор» — роль, и назначать её по имени файла нельзя.
ORCHESTRATORS: tuple[str, ...] = (
    "spa_core/paper_trading/cycle_runner.py",
)


@dataclass(frozen=True)
class Stage:
    """Одна ступень карты §46 и её объявленный эквивалент в дереве."""

    key: str
    owner_name: str               #: имя ступени ДОСЛОВНО из §46
    module: str                   #: путь эквивалента от корня репозитория
    product: str                  #: имя файла-продукта, либо "" для рода human
    kind: str                     #: "artifact" | "human"
    entry: tuple[str, ...] = ()   #: функции, чей ВОЗВРАТ и есть продукт ступени
    contract: tuple[str, ...] = ()  #: для рода human — признаки, ПРОВЕРЯЕМЫЕ в модуле
    why: str = ""                 #: почему эквивалентом объявлен именно он


#: Десять ступеней §46 в порядке владельца. Состав — ЗАМЕР дерева (цикл #515),
#: а не список из головы: у каждой названы модуль и продукт, и оба проверяются
#: разбором. Устаревшее объявление обязано выйти громким ``UNCHECKED``.
STAGES: tuple[Stage, ...] = (
    Stage("opportunity_data", "Opportunity Data",
          "spa_core/orchestrator/adapter_orchestrator.py",
          "adapter_orchestrator_status.json", "artifact",
          entry=("run_orchestrator",),
          why="единственный, кто опрашивает пулы и кладёт снимок вселенной"),
    Stage("portfolio_state", "Portfolio State",
          "spa_core/tuner/portfolio_rebalancer.py",
          "current_positions.json", "artifact",
          entry=("rebalance_portfolio",),
          why="книгу пишет только он (замер ADR-251)"),
    Stage("portfolio_optimizer", "Portfolio Optimizer",
          "spa_core/allocator/allocator.py",
          "target_allocation.json", "artifact",
          entry=("allocate",),
          why="StrategyAllocator — главный производитель цели (ADR-251)"),
    Stage("target_allocation", "Target Allocation",
          "spa_core/paper_trading/allocation_rationale.py",
          "allocation_rationale.json", "artifact",
          entry=("write_shadow_rationale",),
          why="цель вместе с обоснованием и версией политики"),
    Stage("rebalance_evaluator", "Rebalance Evaluator",
          "spa_core/paper_trading/rebalance_trigger.py",
          "rebalance_trigger.json", "artifact",
          entry=("evaluate_from_state",),
          why="пять проверок ADR-031: «пора ли перекладывать»"),
    Stage("risk_gate", "Risk Gate",
          "spa_core/paper_trading/risk_gate.py",
          "risk_policy_blocks.json", "artifact",
          entry=("_apply_risk_policy_gate",),
          why="_apply_risk_policy_gate — последняя дверь перед ходом"),
    Stage("execution_planner", "Execution Planner",
          "spa_core/execution/draft_prep.py", "", "human",
          entry=("prepare_draft",),
          contract=("requires_human_signature", "signed"),
          why="уровень A: черновик подписывает ЧЕЛОВЕК (E1, owner-greenlit)"),
    Stage("execution_agent", "Execution Agent",
          "spa_core/execution/router.py", "", "human",
          entry=("supply", "withdraw"),
          contract=("dry_run",),
          why="агента уровня C нет; маршрутизатор держит режим-заглушку"),
    Stage("post_trade_monitor", "Post-Trade Monitor",
          "spa_core/execution/reconciliation.py",
          "execution_reconciliation.json", "artifact",
          entry=("reconcile",),
          why="сверка «что планировали» против «что стои́т»"),
    Stage("reporting", "Reporting",
          "spa_core/reporting/daily_report.py",
          "daily_report_{date}.json", "artifact",
          entry=("generate_daily_report",),
          why="снимок дня для владельца; equity_curve — его ВХОД, не продукт"),
)


# ───────────────────────── происхождение строкового значения ──────────────────

def _call_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _atoms(node: ast.AST) -> set[tuple[str, str]]:
    """Атомы происхождения под узлом, НЕ спускаясь в контейнеры.

    Элемент словаря/списка путём не становится: именно на этом первая редакция
    объявила себя же писателем чужого артефакта.
    """
    out: set[tuple[str, str]] = set()
    stack: list[ast.AST] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
            out.add(("s", cur.value))
            continue
        if isinstance(cur, ast.Name):
            out.add(("n", cur.id))
            continue
        if isinstance(cur, ast.Call):
            fn = _call_name(cur)
            if fn:
                out.add(("f", fn))
        if isinstance(cur, _CONTAINERS):
            continue
        stack.extend(ast.iter_child_nodes(cur))
    return out


def _symbol_strings(tree: ast.AST) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Имя → строки, ПРОИСХОДЯЩИЕ от него; функция → строки её ``return``."""
    raw_names: dict[str, set[tuple[str, str]]] = {}
    raw_funcs: dict[str, set[tuple[str, str]]] = {}

    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and n.value is not None:
            a = _atoms(n.value)
            for t in n.targets:
                if isinstance(t, ast.Name):
                    raw_names.setdefault(t.id, set()).update(a)
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            if isinstance(n.target, ast.Name):
                raw_names.setdefault(n.target.id, set()).update(_atoms(n.value))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Значение по умолчанию параметра — тоже происхождение: путь вывода
            # аллокатора живёт ровно там (``path=_DEFAULT_OUT``).
            args = n.args
            for arg, default in zip(
                    (args.posonlyargs + args.args)[-len(args.defaults):]
                    if args.defaults else [], args.defaults):
                raw_names.setdefault(arg.arg, set()).update(_atoms(default))
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                if default is not None:
                    raw_names.setdefault(arg.arg, set()).update(_atoms(default))
            for r in ast.walk(n):
                if isinstance(r, ast.Return) and r.value is not None:
                    raw_funcs.setdefault(n.name, set()).update(_atoms(r.value))

    names: dict[str, set[str]] = {k: set() for k in raw_names}
    funcs: dict[str, set[str]] = {k: set() for k in raw_funcs}
    for _ in range(12):                       # неподвижная точка; глубина мала
        changed = False
        for table, raw in ((names, raw_names), (funcs, raw_funcs)):
            for key, items in raw.items():
                cur = table[key]
                before = len(cur)
                for kind, val in items:
                    if kind == "s":
                        cur.add(val)
                    elif kind == "n":
                        cur.update(names.get(val, ()))
                    else:
                        cur.update(funcs.get(val, ()))
                changed = changed or len(cur) != before
        if not changed:
            break
    return names, funcs


def _resolve(node: ast.AST, names: dict[str, set[str]],
             funcs: dict[str, set[str]]) -> set[str]:
    out: set[str] = set()
    for kind, val in _atoms(node):
        if kind == "s":
            out.add(val)
        elif kind == "n":
            out.update(names.get(val, ()))
        else:
            out.update(funcs.get(val, ()))
    return out


def _call_arg_strings(call: ast.Call, names: dict[str, set[str]],
                      funcs: dict[str, set[str]]) -> set[str]:
    """Строки, доходящие до вызова, — аргументом ИЛИ получателем.

    ``path.read_text()`` не имеет аргументов вовсе: путь здесь получатель. Пока
    обход смотрел только в аргументы, читатели снимка оркестратора были
    невидимы, и три стыка подряд выходили ложно односторонними.
    """
    nodes: list[ast.AST] = list(call.args) + [k.value for k in call.keywords
                                              if k.value]
    if isinstance(call.func, ast.Attribute):
        nodes.append(call.func.value)
    out: set[str] = set()
    for node in nodes:
        out.update(_resolve(node, names, funcs))
    return out


# ───────────────────────────── сайты продукта ─────────────────────────────────

def _external_names(tree: ast.AST, modules: dict[str, ast.AST]) -> dict[str, set[str]]:
    """Имена, ВВЕЗЁННЫЕ из соседнего модуля, вместе с их строками.

    Имя файла нередко живёт в чужой константе: ``risk_gate`` пишет
    ``risk_policy_blocks.json``, а сам литерал объявлен в
    ``daily_telegram_report``. Пока резолвер был строго помодульным, писатель
    этого продукта выходил «не найден» — верное утверждение о приборе и
    неверное о дереве. Глубина ОДИН уровень: дальше цепочка перестаёт быть
    происхождением и становится догадкой.
    """
    out: dict[str, set[str]] = {}
    for n in ast.walk(tree):
        if not isinstance(n, ast.ImportFrom) or not n.module:
            continue
        rel = n.module.replace(".", "/") + ".py"
        src = modules.get(rel) or modules.get(rel[:-3] + "/__init__.py")
        if src is None:
            continue
        src_names, _src_funcs = _symbols_cached(src)
        for a in n.names:
            vals = src_names.get(a.name)
            if vals:
                out.setdefault(a.asname or a.name, set()).update(vals)
    return out


#: Таблицы происхождения строятся разбором всего модуля и переиспользуются:
#: без кэша ``measure`` пересобирал бы их ~10 раз на каждый из ~2000 модулей
#: (замер: 50 с на прогон против 6 с с кэшем).
_SYMBOLS: dict[int, tuple[dict[str, set[str]], dict[str, set[str]]]] = {}


def _symbols_cached(tree: ast.AST) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    hit = _SYMBOLS.get(id(tree))
    if hit is None:
        hit = _symbol_strings(tree)
        _SYMBOLS[id(tree)] = hit
    return hit


def product_sites(tree: ast.AST, product: str,
                  external: dict[str, set[str]] | None = None) -> dict[str, bool]:
    """Есть ли в модуле САЙТ записи / чтения продукта (не упоминание)."""
    docs = _docstring_ids(tree)
    base_names, funcs = _symbols_cached(tree)
    names = base_names
    if external:
        names = {k: set(v) for k, v in base_names.items()}
        for k, v in external.items():
            names.setdefault(k, set()).update(v)
    write = read = mention = False
    for n in ast.walk(tree):
        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docs and n.value == product):
            mention = True
        if not isinstance(n, ast.Call):
            continue
        name = _call_name(n)
        if name not in _WRITE_FUNCS and name not in _READ_FUNCS:
            continue
        if product not in _call_arg_strings(n, names, funcs):
            continue
        if name in _WRITE_FUNCS:
            write = True
        else:
            read = True
    return {"write": write, "read": read, "mention": mention}


def _imported_names_from(tree: ast.AST, module_dotted: str) -> set[str]:
    """Имена, ввезённые ИЗ указанного модуля (``from X import f`` → ``{f}``)."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == module_dotted:
            out.update(a.asname or a.name for a in n.names)
    return out


def _names_bound_to_calls(tree: ast.AST, funcs: set[str]) -> set[str]:
    """Имена, чьё значение ПРОИСХОДИТ от вызова одной из ``funcs``.

    Учитывается и вызов на экземпляре: ``a = StrategyAllocator(...)`` даёт
    ``a``, а ``r = a.allocate(...)`` — ``r``.
    """
    out: set[str] = set()
    for _ in range(4):                        # экземпляр → его метод → …
        before = len(out)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign) or n.value is None:
                continue
            hit = False
            for c in ast.walk(n.value):
                if not isinstance(c, ast.Call):
                    continue
                if _call_name(c) in funcs:
                    hit = True
                f = c.func
                if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                        and f.value.id in out):
                    hit = True
            if not hit:
                continue
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        if len(out) == before:
            break
    return out


def _written_via_proxy(tree: ast.AST, product: str, module_dotted: str,
                       external: dict[str, set[str]] | None = None) -> bool:
    """Модуль пишет продукт значением, ПРОИСХОДЯЩИМ от объявленной ступени.

    Урок ADR-251 «решать и записывать — разные роли»: вердикт
    ``rebalance_trigger`` в файл кладёт ``cycle_runner``.
    """
    imported = _imported_names_from(tree, module_dotted)
    if not imported:
        return False
    produced = _names_bound_to_calls(tree, imported)
    if not produced:
        return False
    base_names, funcs = _symbols_cached(tree)
    names = {k: set(v) for k, v in base_names.items()} if external else base_names
    for k, v in (external or {}).items():
        names.setdefault(k, set()).update(v)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or _call_name(n) not in _WRITE_FUNCS:
            continue
        if product not in _call_arg_strings(n, names, funcs):
            continue
        for node in n.args:
            for c in ast.walk(node):
                if isinstance(c, ast.Name) and c.id in produced:
                    return True
    return False


def _defines(tree: ast.AST, names: tuple[str, ...]) -> set[str]:
    """Какие из объявленных входов ступень действительно ОПРЕДЕЛЯЕТ."""
    have = {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return {n for n in names if n in have}


def _produced_by(tree: ast.AST, entries: set[str]) -> set[str]:
    """Имена, чьё значение ПРОИСХОДИТ от возврата одного из входов.

    Происхождение переносится и через доступ к полю: ``alloc = x.allocate()``
    даёт ``alloc``, а ``target_usd = alloc.target_usd`` — ``target_usd``. Без
    этого переноса носитель «оптимизатор → цель» был бы невидим: в
    ``cycle_runner`` в следующую ступень уезжает именно поле результата, а не
    сам результат. Контейнер происхождением не является (:func:`_atoms`).
    """
    out: set[str] = set()
    for _ in range(6):                        # неподвижная точка
        before = len(out)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign) or n.value is None:
                continue
            atoms = _atoms(n.value)
            hit = any(k == "f" and v in entries for k, v in atoms) or \
                  any(k == "n" and v in out for k, v in atoms)
            if not hit:
                continue
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        if len(out) == before:
            break
    return out


def in_process_carrier(tree: ast.AST, up_entries: set[str],
                       down_entries: set[str]) -> bool:
    """Оркестратор ПЕРЕДАЁТ продукт предыдущей ступени следующей — значением.

    Строго сильнее импорта: мало ввезти оба имени и даже позвать оба — значение,
    рождённое входом верхней ступени, обязано дойти до аргумента вызова входа
    нижней. Обратный контроль К5 держит именно эту границу.
    """
    if not up_entries or not down_entries:
        return False
    produced = _produced_by(tree, up_entries)
    if not produced:
        return False
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or _call_name(n) not in down_entries:
            continue
        for node in list(n.args) + [k.value for k in n.keywords if k.value]:
            for kind, val in _atoms(node):
                if kind == "n" and val in produced:
                    return True
    return False


def has_contract(tree: ast.AST, contract: tuple[str, ...]) -> bool:
    """Род ``human`` ПРОВЕРЯЕТСЯ: признак обязан быть виден в самом модуле."""
    if not contract:
        return False
    docs = _docstring_ids(tree)
    seen: set[str] = {n.value for n in ast.walk(tree)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)
                      and id(n) not in docs}
    for n in ast.walk(tree):
        if isinstance(n, ast.keyword) and n.arg:
            seen.add(n.arg)
        elif isinstance(n, ast.Name):
            seen.add(n.id)
        elif isinstance(n, ast.Attribute):
            seen.add(n.attr)
        elif isinstance(n, ast.arg):
            seen.add(n.arg)
    return all(tok in seen for tok in contract)


# ───────────────────────────── разбор всего дерева ────────────────────────────

def _module_dotted(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".py") else rel
    return stem.replace("/", ".")


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None


#: Сам измеритель в измеряемое дерево НЕ входит. Он называет каждый продукт по
#: имени в :data:`STAGES`, поэтому без этого исключения объявлял бы себя
#: читателем всего, что меряет: ``execution_reconciliation.json`` первым же
#: прогоном получил «потребителя», которым был этот самый файл. Сторож,
#: кормящий свой же корпус, меряет себя, а не дерево.
_SELF = "spa_core/monitoring/cio_component_map.py"


def _iter_modules(root: Path) -> Iterable[tuple[str, ast.AST]]:
    """Все модули дерева, кроме тестов и самого измерителя.

    Тест читает продукт по обязанности, и считать его читателем значило бы
    объявить связанной любую ступень."""
    for base in ("spa_core", "scripts"):
        d = root / base
        if not d.is_dir():
            continue
        for py in sorted(d.rglob("*.py")):
            rel = py.relative_to(root).as_posix()
            if ("/tests/" in rel or rel == _SELF
                    or rel.rsplit("/", 1)[-1].startswith("test_")):
                continue
            tree = _parse(py)
            if tree is not None:
                yield rel, tree


def measure(root: Path, stages: tuple[Stage, ...] = STAGES) -> dict[str, Any]:
    """Замер: роль каждой ступени + носитель каждого стыка."""
    _SYMBOLS.clear()   # id() переиспользуется после сборки мусора: кэш живёт
                       # ровно один замер, иначе чужая таблица притворится своей
    modules = dict(_iter_modules(root))
    ext: dict[str, dict[str, set[str]]] = {
        rel: _external_names(tree, modules) for rel, tree in modules.items()}
    orchestrators = {rel: modules[rel] for rel in ORCHESTRATORS if rel in modules}

    role: dict[str, dict[str, Any]] = {}
    readers: dict[str, list[str]] = {}
    registry: dict[str, list[str]] = {}
    entries: dict[str, set[str]] = {}
    for st in stages:
        tree = modules.get(st.module)
        if tree is None:
            role[st.key] = {"verdict": "UNCHECKED", "writer": "",
                            "reason": f"объявленного модуля нет в дереве: {st.module}"}
            continue
        defined = _defines(tree, st.entry)
        entries[st.key] = defined
        if set(st.entry) - defined:
            role[st.key] = {
                "verdict": "UNCHECKED", "writer": "",
                "reason": (f"объявленный вход {', '.join(sorted(set(st.entry) - defined))} "
                           f"в {st.module} не определён — объявление устарело"),
            }
            continue
        if st.kind == "human":
            ok = has_contract(tree, st.contract)
            role[st.key] = {
                "verdict": "PERFORMED_HUMAN" if ok else "UNCHECKED",
                "writer": "",
                "reason": "" if ok else
                          (f"род объявлен `human`, но контракта "
                           f"({', '.join(st.contract)}) в {st.module} нет — "
                           "объявление устарело"),
            }
            continue
        if product_sites(tree, st.product, ext.get(st.module))["write"]:
            role[st.key] = {"verdict": "PERFORMED", "writer": st.module, "reason": ""}
        else:
            proxies = [rel for rel, t in modules.items()
                       if _written_via_proxy(t, st.product, _module_dotted(st.module),
                                             ext.get(rel))]
            if proxies:
                role[st.key] = {"verdict": "PERFORMED_VIA_ORCHESTRATOR",
                                "writer": proxies[0], "reason": ""}
            else:
                plain = [rel for rel, t in modules.items()
                         if product_sites(t, st.product, ext.get(rel))["write"]]
                role[st.key] = {
                    "verdict": "UNCHECKED",
                    "writer": plain[0] if plain else "",
                    "reason": (f"продукт `{st.product}` объявлен за {st.module}, "
                               f"но сайта записи у него нет; пишут: "
                               f"{', '.join(plain) if plain else 'никто'}"),
                }
        sites = {rel: product_sites(t, st.product, ext.get(rel))
                 for rel, t in modules.items() if rel != st.module}
        readers[st.key] = sorted(r for r, v in sites.items() if v["read"])
        # Реестровый потребитель: имя продукта стои́т в таблице артефактов, а
        # путь собирается в цикле по этой таблице — статикой такой сайт чтения
        # не виден. Назвать это «не читает никто» значило бы выдать слепоту
        # прибора за разрыв цепи (шаг 0-офис читает продукт именно так).
        registry[st.key] = sorted(
            r for r, v in sites.items() if v["mention"] and not v["read"])

    edges: list[dict[str, Any]] = []
    for up, down in zip(stages, stages[1:]):
        edge: dict[str, Any] = {
            "from": up.key, "to": down.key,
            "from_name": up.owner_name, "to_name": down.owner_name,
            "product": up.product, "carrier": "", "readers": [], "note": "",
        }
        # Стык, у которого ЛЮБОЙ конец — ступень рода ``human``, пересекает
        # границу «машина ↔ человек»: там носителем и должен быть человек
        # (``draft_prep``: рекомендация переходит границу «as plain DATA, never
        # a code import»; инвариант #6 запрещает paper-пути импорт execution).
        # Требовать здесь машинный носитель — верный ответ на не тот вопрос.
        if up.kind == "human" or down.kind == "human":
            edge.update(verdict="BY_DESIGN_HUMAN",
                        note=("стык пересекает границу «машина ↔ человек»; "
                              "машинного носителя здесь быть не должно"))
            edges.append(edge)
            continue
        if role[up.key]["verdict"] == "UNCHECKED":
            edge.update(verdict="UNCHECKED",
                        note=f"роль источника не измерена: {role[up.key]['reason']}")
            edges.append(edge)
            continue
        rd = readers.get(up.key, [])
        edge["readers"] = rd
        down_tree = modules.get(down.module)
        if down_tree is None:
            edge.update(verdict="UNCHECKED",
                        note=f"модуля следующей ступени нет в дереве: {down.module}")
        elif product_sites(down_tree, up.product, ext.get(down.module))["read"]:
            edge.update(verdict="WIRED", carrier="artifact")
        else:
            via = [rel for rel, t in orchestrators.items()
                   if in_process_carrier(t, entries.get(up.key, set()),
                                         entries.get(down.key, set()))]
            if via:
                edge.update(verdict="WIRED_IN_PROCESS", carrier=f"in_process:{via[0]}")
            elif rd:
                edge.update(verdict="ONE_WAY",
                            note=("продукт читают, но НЕ следующая ступень карты, "
                                  "и оркестратор его ей не передаёт"))
            elif registry.get(up.key):
                edge.update(verdict="ONE_WAY",
                            registry_consumers=registry[up.key],
                            note=("сайта чтения нет ни у кого; продукт значится "
                                  "в реестре артефактов "
                                  f"({', '.join(registry[up.key])}) — его читает "
                                  "отчётность, а не следующая ступень"))
            else:
                edge.update(verdict="DEAD_END",
                            note="продукт не получает никто, кроме производителя")
        edges.append(edge)
    return {"role": role, "readers": readers, "registry": registry,
            "entries": {k: sorted(v) for k, v in entries.items()}, "edges": edges}


# ─────────────────────────── положительный контроль ───────────────────────────

_UP = ('from spa_core.utils.atomic import atomic_save\n'
       'NAME = "k_probe.json"\n'
       'def run(d):\n'
       '    atomic_save({"a": 1}, str(d / NAME))\n'
       '    return {"a": 1}\n')
_DOWN_READS = ('import json\n'
               'def read(d):\n'
               '    return json.loads(open(str(d / "k_probe.json")).read())\n')
_DOWN_BLIND = 'def read(d):\n    return 0\n'
_DOWN_IMPORTS = ('from spa_core.probe_up import run\n'
                 'def read(d):\n'
                 '    run(d)\n'          # импортирует И зовёт соседа
                 '    return 0\n')       # но продукта НЕ читает
_ORCH_CARRIES = ('from spa_core.probe_up import run\n'
                 'from spa_core.probe_down import read\n'
                 'def cycle(d):\n'
                 '    res = run(d)\n'
                 '    return read(res)\n')
_ORCH_BLIND = ('from spa_core.probe_up import run\n'
               'from spa_core.probe_down import read\n'
               'def cycle(d):\n'
               '    run(d)\n'            # зовёт обе ступени…
               '    return read(d)\n')   # …но результат не передаёт


def positive_control() -> dict[str, Any]:
    """Пять сцен; не выполнена любая ⇒ счёт читать нельзя.

    Сцены разбираются в памяти: живое дерево не читается и не пишется.
    """
    up = ast.parse(_UP)
    checks = {
        # К1 — проба умеет сказать «связано».
        "k1_can_say_wired": (product_sites(up, "k_probe.json")["write"]
                             and product_sites(ast.parse(_DOWN_READS),
                                               "k_probe.json")["read"]),
        # К2 — проба умеет сказать «не связано».
        "k2_can_say_dead_end": not product_sites(ast.parse(_DOWN_BLIND),
                                                 "k_probe.json")["read"],
        # К3, обратный — импорт и вызов соседа связью НЕ являются.
        "k3_import_is_not_wiring": not product_sites(ast.parse(_DOWN_IMPORTS),
                                                     "k_probe.json")["read"],
        # К4 — второй носитель умеет сказать «да».
        "k4_in_process_can_say_yes": in_process_carrier(
            ast.parse(_ORCH_CARRIES), {"run"}, {"read"}),
        # К5, обратный — «обе ступени вызваны» носителем НЕ является.
        "k5_calling_both_is_not_carrying": not in_process_carrier(
            ast.parse(_ORCH_BLIND), {"run"}, {"read"}),
    }
    return {"passed": all(checks.values()), "checks": checks}


# ───────────────────────────────── отчёт ──────────────────────────────────────

def _findings(meas: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for e in meas["edges"]:
        head = f"{e['from_name']} → {e['to_name']}"
        if e["verdict"] == "DEAD_END":
            out.append({"severity": "critical",
                        "text": (f"стык «{head}» разорван: продукт "
                                 f"`{e['product']}` не получает никто, кроме "
                                 "производителя — ступень работу карты не делает")})
        elif e["verdict"] == "ONE_WAY" and not e["readers"]:
            reg = ", ".join(e.get("registry_consumers", [])) or "никто"
            out.append({"severity": "critical",
                        "text": (f"ОСТРОВ на стыке «{head}»: `{e['product']}` не "
                                 "читает как данные НИ ОДИН модуль; он значится "
                                 f"лишь в реестре артефактов ({reg}), то есть его "
                                 "читает отчётность. Ступень производит вердикт, "
                                 "по которому ход не идёт")})
        elif e["verdict"] == "ONE_WAY":
            rd = ", ".join(e["readers"][:4]) + ("…" if len(e["readers"]) > 4 else "")
            out.append({"severity": "warn",
                        "text": (f"цепь расходится с картой на стыке «{head}»: "
                                 f"`{e['product']}` берут {len(e['readers'])} "
                                 f"модул(я/ей) ({rd}), но следующая ступень карты "
                                 "его не берёт ни файлом, ни значением")})
        elif e["verdict"] == "UNCHECKED":
            out.append({"severity": "unchecked", "text": f"{head}: {e['note']}"})
    for key, r in meas["role"].items():
        if r["verdict"] == "UNCHECKED":
            out.append({"severity": "unchecked",
                        "text": f"роль ступени `{key}` не измерена: {r['reason']}"})
    return out


def run(root: str | Path | None = None, *, write: bool = True,
        now: datetime | None = None) -> dict[str, Any]:
    """Собрать отчёт §46. ``now`` — ВХОД (правило о времени в тестах)."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    ts = (now or datetime.now(timezone.utc)).isoformat()

    control = positive_control()
    meas = measure(root)
    findings = _findings(meas)

    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "critical"),
        "warn": sum(1 for f in findings if f["severity"] == "warn"),
        "info": 0,
        "unchecked": sum(1 for f in findings if f["severity"] == "unchecked"),
    }
    wired = sum(1 for e in meas["edges"]
                if e["verdict"] in ("WIRED", "WIRED_IN_PROCESS"))
    present = sum(1 for r in meas["role"].values()
                  if r["verdict"] != "UNCHECKED")

    if not control["passed"]:
        overall = "UNCHECKED"
    elif counts["critical"]:
        overall = "CRITICAL"
    elif counts["unchecked"]:
        overall = "UNCHECKED"
    elif counts["warn"]:
        overall = "WARN"
    else:
        overall = "OK"

    doc = {
        "schema": "cio_component_map/v1",
        "generated_at": ts,
        "overall": overall,
        "counts": counts,
        "positive_control": control,
        "stages_declared": [
            {"key": s.key, "owner_name": s.owner_name, "module": s.module,
             "product": s.product, "kind": s.kind, "why": s.why}
            for s in STAGES
        ],
        "stages": meas["role"],
        "stages_present": present,
        "stages_total": len(STAGES),
        "readers": meas["readers"],
        "registry_consumers": meas["registry"],
        "entries_measured": meas["entries"],
        "edges": meas["edges"],
        "edges_wired": wired,
        "edges_total": len(meas["edges"]),
        "orchestrators": list(ORCHESTRATORS),
        "findings": findings,
        "advisory": ("ADVISORY: ни один порог не изменён, ни одна ступень не "
                     "перенесена. Соединить разорванный стык — правка "
                     "money-path и решение владельца."),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(root) / REPORT_REL))
    return doc


def main() -> int:
    doc = run(root=os.environ.get("SPA_ROOT") or None)
    print(f"cio_component_map: {doc['overall']} "
          f"(critical={doc['counts']['critical']} "
          f"unchecked={doc['counts']['unchecked']}) · "
          f"ступеней с эквивалентом {doc['stages_present']}/{doc['stages_total']} · "
          f"стыков несут ход {doc['edges_wired']}/{doc['edges_total']}")
    for f in doc["findings"]:
        print(f"  [{f['severity'].upper()}] {f['text']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
