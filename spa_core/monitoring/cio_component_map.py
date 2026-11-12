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

Третий вопрос §46 (ADR-991, цикл #1109): ТО ЛИ значение доходит до ступени?
============================================================================
Стык ``WIRED_IN_PROCESS`` верен и недостаточен: имя, рождённое ``allocate()``,
доходит до ``write_shadow_rationale`` — но между двумя вызовами его
ПЕРЕСВЯЗЫВАЮТ девять присваиваний (ADR-989 насчитал их чтением строк 1631–2404),
и семь делают функции, которых в карте владельца НЕТ: стоп-кран, мягкий дерискинг,
ADR-002, постура RTMR, псевдонимы пулов, трим ADR-850. «Состав 10/10, строить
нечего» (ADR-253) был ответом о ПРОПИСАННЫХ ступенях; о непрописанных карта не
знала по построению — ровно то, что владелец запретил словами «не создавать
новые компоненты, если эквиваленты уже существуют».

:func:`carrier_rewriters` — площадка есть присваивание в том же теле функции,
строго между входами, ПЕРЕсвязывающее имя носителя значением с вызовом. Первое
связывание производного имени — не переписчик (найдено на себе:
``_policy_refusals = quantify_policy_refusals(...)``); ``dict(gate[...])``
приписывается тому, кто связал ``gate``. Вызов входа ДРУГОЙ ступени карты —
«прописанная не на своём стыке» (Risk Gate стои́т в живом цикле ДО Target
Allocation), всё прочее — СКРЫТАЯ ступень.

:func:`stage_order` — порядок ПЕРВОГО вызова входов на СКВОЗНОМ пути, приведённый к
корню по графу вызовов (голым именем: ``_mod2.main()`` — чужой модуль, и первая
редакция замыкала граф в кольцо). Ветка раннего выхода (``if not live: … return``)
на путь не ложится — иначе ветка «данных нет» читалась бы как порядок торгового
дня. Это ПРОКСИ: строка ≠ исполнение, позиции печатаются целиком.

Исходы оси: ``measured`` (в т. ч. «измерено и равно нулю») · ``unmeasured`` с
причиной (входы в разных функциях, корня нет) · ``not_applicable`` для файлового
носителя. Ступень вне сквозного пути — ``off_path``, не вызванная — ``unreached``;
ни то, ни другое не инверсия и не ноль.

Положительный контроль — условие ВСЕГО отчёта
=============================================
«Читателя нет» ничего не значит, если проба слепа. Счёт читается, только если
выполнены ДЕВЯТЬ условий (:func:`positive_control`); не выполнено любое ⇒
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
**К6** проба переписчиков видит СКРЫТУЮ ступень между входами.
**К7, обратный** — псевдоним без вызова и первое связывание производного имени
переписчиками НЕ являются (ноль на чистом носителе).
**К8** проба порядка видит инверсию против порядка владельца.
**К9, обратный** — цикл в порядке владельца даёт ноль инверсий, а вызов в ветке
раннего выхода не ложится на путь.
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
#:
#: Кэш живёт НА САМОМ дереве (атрибут узла), а не в словаре по ``id(tree)``.
#: Словарь по адресу был дефектом (найдено 16.09 при доставке ADR-400): записи
#: никогда не вытеснялись, а адрес освобождённого дерева переиспользуется
#: следующим ``ast.parse`` — и новое дерево получало таблицы ЧУЖОГО модуля.
#: Проявлялось как плавающее падение ``test_receiver_of_a_method_call_is_a_site``
#: (в одиночку зелёный, в составе файла — ``read=False``), зависящее от раскладки
#: памяти, то есть от любого соседнего изменения в дереве. Атрибут узла умирает
#: вместе с деревом и по построению не может достаться другому.
_SYMBOLS_ATTR = "_spa_cio_symbols"


def _symbols_cached(tree: ast.AST) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    hit = getattr(tree, _SYMBOLS_ATTR, None)
    if hit is None:
        hit = _symbol_strings(tree)
        try:
            setattr(tree, _SYMBOLS_ATTR, hit)
        except Exception:  # noqa: BLE001 — узел без __dict__: работаем без кэша
            pass
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
    # Кэш таблиц живёт на узлах деревьев (см. `_symbols_cached`) и умирает вместе с
    # ними; чистить по адресам больше нечего — деревья замера рождаются здесь заново.
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

    # Третья ось (ADR-991): на стыке, который несёт ход значением, — кто
    # ПЕРЕСВЯЗЫВАЕТ носитель между входами; и порядок первого вызова входов.
    declared = {e: st.key for st in stages for e in st.entry}
    for edge in edges:
        if edge["verdict"] != "WIRED_IN_PROCESS":
            edge["rewriters"] = {"verdict": "not_applicable",
                                 "reason": "носитель не в памяти оркестратора"}
            continue
        rel = edge["carrier"].split(":", 1)[1]
        edge["rewriters"] = carrier_rewriters(
            orchestrators[rel], entries.get(edge["from"], set()),
            entries.get(edge["to"], set()), declared)
    human = frozenset(st.key for st in stages if st.kind == "human")
    order = {rel: stage_order(tree, {st.key: set(st.entry) for st in stages},
                              tuple(st.key for st in stages), human)
             for rel, tree in orchestrators.items()}
    return {"role": role, "readers": readers, "registry": registry,
            "entries": {k: sorted(v) for k, v in entries.items()}, "edges": edges,
            "order": order}


# ───────── переписчики носителя и порядок ступеней (ADR-991, перемер §46 #1109) ─────────
#
# Третий вопрос §46, которого не было у первых двух: **то ли самое значение доходит
# до следующей ступени, что произвела предыдущая?** Стык «Portfolio Optimizer →
# Target Allocation» с цикла #515 числится ``WIRED_IN_PROCESS`` — и это верно: имя,
# рождённое ``allocate()``, доходит до аргумента ``write_shadow_rationale``. Но между
# двумя вызовами то же имя ПЕРЕСВЯЗЫВАЮТ девять присваиваний (замер ADR-989,
# строки 1631–2404 ``cycle_runner``), и семь из девяти делают функции, которых в
# карте владельца нет: стоп-кран, мягкий дерискинг, ADR-002, постура RTMR,
# псевдонимы пулов, трим ADR-850. Карта говорила «состав 10/10, строить нечего» —
# о ПРОПИСАННЫХ ступенях; о непрописанных она не знала по построению.
#
# Второй вопрос той же оси — ПОРЯДОК: владелец назвал цепь упорядоченной
# (Target Allocation → Rebalance Evaluator → Risk Gate), а живой цикл зовёт входы
# в своём порядке. Мера — ПЕРВАЯ строка вызова входа, приведённая к общему корню
# через граф вызовов функций оркестратора (вызов внутри помощника стои́т там, где
# стои́т вызов помощника). Это ПРОКСИ: строка не равна исполнению при ветвлении,
# и прибор печатает позиции целиком, чтобы читатель судил сам. Мерить порядок
# динамикой значило бы запускать дневной цикл — против живого ``data/`` нельзя.

#: Конструкторы-копии: ``target_usd = dict(gate["target_usd"])`` переписывает
#: носитель не сам — его переписал тот, кто связал ``gate``. Площадка
#: приписывается ЕМУ, иначе два трима RiskPolicy читались бы как «dict».
_COPY_CTORS = {"dict", "list", "tuple", "set", "frozenset", "sorted",
               "copy", "deepcopy"}

#: Предел глубины графа вызовов при приведении строки к корню.
_CALL_DEPTH = 12


def _target_names(node: ast.AST) -> set[str]:
    """Имена, которые связывает цель присваивания (``Name`` либо распаковка)."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        out: set[str] = set()
        for e in node.elts:
            out |= _target_names(e)
        return out
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return set()


def _defs(tree: ast.AST) -> list[ast.AST]:
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _enclosing_def(tree: ast.AST, lineno: int) -> ast.AST | None:
    """Самая ВНУТРЕННЯЯ функция, в чьи строки попадает ``lineno``."""
    best = None
    for n in _defs(tree):
        end = getattr(n, "end_lineno", None) or n.lineno
        if n.lineno <= lineno <= end and (best is None or n.lineno > best.lineno):
            best = n
    return best


def _early_exit_ranges(fn: ast.AST) -> list[tuple[int, int]]:
    """Строки веток ``if``/``else``, которые кончаются ``return``/``raise``, ПОКА за
    самим ``if`` в том же блоке ещё есть операторы.

    Такая ветка — РАННИЙ ВЫХОД (``if not live: … return result``): вызов в ней не
    лежит на сквозном пути функции, и судить по нему о порядке ступеней значило бы
    читать ветку «данных нет» как порядок торгового дня (найдено на себе, #1109:
    ``_run_daily_report`` в ``cycle_runner`` зовётся ТОЛЬКО там). Хвост функции
    (``return`` последним оператором) и ``try`` ранним выходом НЕ являются —
    первая редакция считала их таковыми и объявила весь цикл «вне пути».
    """
    out: list[tuple[int, int]] = []

    def block(stmts: list[ast.stmt]) -> None:
        for i, st in enumerate(stmts):
            follows = i < len(stmts) - 1
            if isinstance(st, ast.If):
                for br in (st.body, st.orelse):
                    if br and follows and isinstance(br[-1], (ast.Return, ast.Raise)):
                        out.append((br[0].lineno,
                                    getattr(br[-1], "end_lineno", br[-1].lineno)))
                    block(br)
                continue
            for attr in ("body", "orelse", "finalbody"):
                sub = getattr(st, attr, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    block(sub)
            for h in getattr(st, "handlers", []) or []:
                block(h.body)

    block(list(getattr(fn, "body", [])))
    return out


def _in_returning_branch(fn: ast.AST, lineno: int,
                         ranges: list[tuple[int, int]] | None = None) -> bool:
    """Стои́т ли строка в ветке раннего выхода функции (см. :func:`_early_exit_ranges`)."""
    for a, b in (ranges if ranges is not None else _early_exit_ranges(fn)):
        if a <= lineno <= b:
            return True
    return False


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """``from m import f as g`` → ``{g: f}``: вызов ``g(...)`` есть вызов входа ``f``."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.asname and a.asname != a.name:
                    out[a.asname] = a.name
    return out


def _call_args(call: ast.Call) -> list[ast.AST]:
    return list(call.args) + [k.value for k in call.keywords if k.value is not None]


def _entry_calls(tree: ast.AST, entries: set[str],
                 aliases: dict[str, str]) -> list[ast.Call]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            nm = _call_name(n)
            if aliases.get(nm, nm) in entries:
                out.append(n)
    return sorted(out, key=lambda c: c.lineno)


def carrier_rewriters(tree: ast.AST, up_entries: set[str], down_entries: set[str],
                      declared: dict[str, str]) -> dict[str, Any]:
    """Кто ПЕРЕСВЯЗЫВАЕТ носитель между входом верхней ступени и входом нижней.

    Носитель — имена, рождённые возвратом верхнего входа, которые доходят до
    аргумента нижнего (та же мера, что у :func:`in_process_carrier`). Площадка —
    присваивание в том же теле функции, строго между двумя вызовами, связывающее
    имя носителя значением, в котором есть ВЫЗОВ. Псевдоним без вызова
    (``x = y``) переписчиком не является. ``declared`` — вход → ключ прописанной
    ступени; вызов входа другой ступени карты здесь — «прописанная не на своём
    стыке», всё прочее — СКРЫТАЯ ступень.

    Три исхода: ``measured`` · ``unmeasured`` с причиной (входы в разных функциях
    или не найдены — строка там порядком не является) · пустой список площадок
    при ``measured`` — «измерено и равно нулю».
    """
    base: dict[str, Any] = {"function": "", "span": [], "carried": [], "sites": [],
                            "hidden": [], "declared_out_of_place": []}
    aliases = _import_aliases(tree)
    # Вход, ввезённый под псевдонимом (``rebalance_portfolio as _rb``), рождает
    # носитель под псевдонимом же — происхождение ищется по обоим именам.
    up_names = set(up_entries) | {a for a, n in aliases.items() if n in up_entries}
    produced = _produced_by(tree, up_names)
    if not produced:
        return {**base, "verdict": "unmeasured",
                "reason": "возврат входа верхней ступени не связан ни с одним именем"}
    ups = _entry_calls(tree, up_entries, aliases)
    if not ups:
        return {**base, "verdict": "unmeasured",
                "reason": "вызова входа верхней ступени в оркестраторе нет"}
    up_call = ups[0]
    downs = []
    for c in _entry_calls(tree, down_entries, aliases):
        carried = {v for node in _call_args(c) for k, v in _atoms(node)
                   if k == "n" and v in produced}
        if carried and c.lineno > up_call.lineno:
            downs.append((c, carried))
    if not downs:
        return {**base, "verdict": "unmeasured",
                "reason": ("ни один вызов входа нижней ступени после входа верхней "
                           "не получает её продукт аргументом")}
    down_call, carried = downs[0]
    fn_up = _enclosing_def(tree, up_call.lineno)
    fn_down = _enclosing_def(tree, down_call.lineno)
    if fn_up is None or fn_up is not fn_down:
        return {**base, "verdict": "unmeasured",
                "span": [up_call.lineno, down_call.lineno],
                "reason": (f"входы вызываются в разных функциях "
                           f"({getattr(fn_up, 'name', '<модуль>')} / "
                           f"{getattr(fn_down, 'name', '<модуль>')}) — порядок по "
                           "строкам там носителем не является")}
    binders: dict[str, list[tuple[int, str]]] = {}
    first_bind: dict[str, int] = {}
    for n in ast.walk(fn_up):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            for nm in _target_names(t):
                first_bind[nm] = min(first_bind.get(nm, n.lineno), n.lineno)
                if isinstance(n.value, ast.Call):
                    cn = _call_name(n.value)
                    binders.setdefault(nm, []).append((n.lineno, aliases.get(cn, cn)))
    sites: list[dict[str, Any]] = []
    for n in sorted((x for x in ast.walk(fn_up) if isinstance(x, ast.Assign)),
                    key=lambda x: x.lineno):
        if not (up_call.lineno < n.lineno < down_call.lineno):
            continue
        bound: set[str] = set()
        for t in n.targets:
            bound |= _target_names(t)
        # ПЕРЕсвязывание: имя уже было связано раньше. Первое связывание
        # производного имени (``_policy_refusals = quantify(...)``) — не
        # переписчик носителя, а его производная; замер #1109 нашёл это на себе.
        bound = {b for b in bound & carried if first_bind.get(b, n.lineno) < n.lineno}
        if not bound:
            continue
        atoms = _atoms(n.value)
        callees = sorted(v for k, v in atoms if k == "f")
        if not callees:
            continue                       # псевдоним без вызова — не переписчик
        callee = _call_name(n.value) if isinstance(n.value, ast.Call) else callees[0]
        via = ""
        if callee in _COPY_CTORS:
            inner = sorted(v for k, v in atoms if k == "n" and v not in bound)
            for nm in inner:
                cands = [(ln, cl) for ln, cl in binders.get(nm, []) if ln < n.lineno]
                if cands:
                    callee, via = max(cands)[1], nm
                    break
        callee = aliases.get(callee, callee)
        key = declared.get(callee, "")
        sites.append({"line": n.lineno, "bound": sorted(bound), "callee": callee,
                      "via": via, "stage": key,
                      "kind": "declared" if key else "hidden"})
    return {**base, "verdict": "measured", "reason": "", "function": fn_up.name,
            "span": [up_call.lineno, down_call.lineno], "carried": sorted(carried),
            "sites": sites,
            "hidden": sorted({s["callee"] for s in sites if s["kind"] == "hidden"}),
            "declared_out_of_place": sorted({s["stage"] for s in sites
                                             if s["kind"] == "declared"})}


def stage_order(tree: ast.AST, stage_entries: dict[str, set[str]],
                owner_order: tuple[str, ...],
                skip: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Порядок ПЕРВОГО вызова входов ступеней в оркестраторе против порядка владельца.

    Позиция — кортеж строк по пути графа вызовов от корня (функции, которую не
    зовёт никто) до вызова входа; вызов внутри помощника стои́т там, где стои́т
    вызов помощника. Корней может быть несколько — берётся тот, под которым
    достижимо больше ступеней, и он ПЕЧАТАЕТСЯ. ``skip`` — ступени, порядок
    которых не меряется по построению (род ``human``). Инверсия — пара ступеней
    владельца, вызванная в обратном порядке.
    """
    aliases = _import_aliases(tree)
    defs = _defs(tree)
    names = {d.name for d in defs}
    # Вызов = (строка, лежит ли он в ветке раннего выхода). Второе поле едет по
    # всему пути: помощник, позванный из ветки ``if not live: … return``, сам
    # стои́т вне сквозного пути, даже если внутри него ветвления нет.
    calls_in: dict[str, dict[str, tuple[bool, int]]] = {d.name: {} for d in defs}
    # Граф «кто кого зовёт» строится ТОЛЬКО по вызовам голым именем: ``x.main()``
    # — чужой модуль, и считать его вызовом своего ``main`` значит замкнуть граф в
    # кольцо (замер #1109: ``_mod2.main()`` в ``cycle_runner`` делал корнем
    # ``_run_fundability_pack``). Входы ступеней меряются и через атрибут.
    graph: dict[str, dict[str, tuple[bool, int]]] = {d.name: {} for d in defs}
    early: dict[str, list[tuple[int, int]]] = {d.name: _early_exit_ranges(d) for d in defs}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = _enclosing_def(tree, n.lineno)
        if fn is None:
            continue
        cn = _call_name(n)
        cn = aliases.get(cn, cn)
        # Предпочтение — вызову на СКВОЗНОМ пути: ``main`` зовёт ``_main_inner``
        # дважды, первый раз в ветке ``--dry-run`` с ранним возвратом (#1109).
        rec = (_in_returning_branch(fn, n.lineno, early[fn.name]), n.lineno)
        cur = calls_in[fn.name]
        if cn not in cur or rec < cur[cn]:
            cur[cn] = rec
        if isinstance(n.func, ast.Name) and cn in names:
            g = graph[fn.name]
            if cn not in g or rec < g[cn]:
                g[cn] = rec
    callers = {f: sorted(c for c, cs in graph.items() if f in cs and c != f)
               for f in names}

    def paths(fname: str, seen: tuple[str, ...] = ()
              ) -> list[tuple[str, tuple[int, ...], bool]]:
        if not callers[fname]:
            return [(fname, (), False)]
        if len(seen) >= _CALL_DEPTH:
            return []
        out = []
        for c in callers[fname]:
            if c in seen:
                continue                   # кольцо — путь обрывается, корня нет
            early, ln = graph[c][fname]
            for root, p, e in paths(c, seen + (fname,)):
                out.append((root, p + (ln,), e or early))
        return out

    occurrences: dict[str, list[tuple[str, tuple[int, ...], str, bool]]] = {}
    for key, entries in stage_entries.items():
        occ = []
        for fname, cs in calls_in.items():
            for e in entries:
                if e in cs:
                    early, ln = cs[e]
                    for root, p, pe in paths(fname):
                        occ.append((root, p + (ln,), fname, pe or early))
        occurrences[key] = occ
    roots_cover: dict[str, set[str]] = {}
    for key, occ in occurrences.items():
        for root, _, _, _ in occ:
            roots_cover.setdefault(root, set()).add(key)
    if not roots_cover:
        return {"verdict": "unmeasured", "reason": "ни один вход ступени в оркестраторе не вызван",
                "root": "", "positions": {}, "off_path": {}, "unreached": sorted(stage_entries),
                "inversions": [], "owner_order": list(owner_order)}
    root = sorted(roots_cover, key=lambda r: (-len(roots_cover[r]), r))[0]
    positions: dict[str, dict[str, Any]] = {}
    off_path: dict[str, dict[str, Any]] = {}
    unreached: list[str] = []
    for key in owner_order:
        if key in skip:
            continue
        occ = sorted((p, f, e) for r, p, f, e in occurrences.get(key, []) if r == root)
        on = [(p, f) for p, f, e in occ if not e]
        if on:
            positions[key] = {"first": list(on[0][0]), "function": on[0][1],
                              "calls": len(occ), "early_return_calls": len(occ) - len(on)}
        elif occ:
            off_path[key] = {"first": list(occ[0][0]), "function": occ[0][1],
                             "calls": len(occ),
                             "reason": "все вызовы входа лежат в ветке раннего выхода"}
        else:
            unreached.append(key)
    inversions = []
    ordered = [k for k in owner_order if k in positions]
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if tuple(positions[a]["first"]) > tuple(positions[b]["first"]):
                inversions.append([a, b])
    live = sorted(ordered, key=lambda k: tuple(positions[k]["first"]))
    if len(positions) < 2:
        return {"verdict": "unmeasured", "reason": "под корнем достижимо меньше двух ступеней",
                "root": root, "positions": positions, "off_path": off_path,
                "unreached": unreached, "inversions": [], "owner_order": list(owner_order),
                "live_order": live}
    return {"verdict": "measured", "reason": "", "root": root, "positions": positions,
            "off_path": off_path, "unreached": unreached, "inversions": inversions,
            "owner_order": [k for k in owner_order if k not in skip], "live_order": live,
            "method": ("позиция = первая строка вызова, приведённая к корню по графу "
                       "вызовов (ПРОКСИ: строка ≠ исполнение при ветвлении)")}


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


_ORCH_REWRITES = ('from spa_core.probe_up import run\n'
                  'from spa_core.probe_down import read\n'
                  'from spa_core.probe_hidden import clamp\n'
                  'def cycle(d):\n'
                  '    res = run(d)\n'
                  '    res = clamp(res)\n'          # скрытая ступень
                  '    return read(res)\n')
_ORCH_CLEAN = ('from spa_core.probe_up import run\n'
               'from spa_core.probe_down import read\n'
               'def cycle(d):\n'
               '    res = run(d)\n'
               '    same = res\n'                   # псевдоним без вызова
               '    extra = len(res)\n'            # первое связывание производного
               '    return read(same, extra)\n')
_ORCH_INVERTED = ('from spa_core.a import first\n'
                  'from spa_core.b import second\n'
                  'def cycle(d):\n'
                  '    second(d)\n'
                  '    first(d)\n')
_ORCH_ORDERED = ('from spa_core.a import first\n'
                 'from spa_core.b import second\n'
                 'def cycle(d, live):\n'
                 '    if not live:\n'
                 '        second(d)\n'             # ранний выход — не путь
                 '        return 0\n'
                 '    first(d)\n'
                 '    second(d)\n')


def positive_control() -> dict[str, Any]:
    """Девять сцен; не выполнена любая ⇒ счёт читать нельзя.

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
    # К6/К7 — переписчики носителя; К8/К9 — порядок (ADR-991).
    rw_hidden = carrier_rewriters(ast.parse(_ORCH_REWRITES), {"run"}, {"read"},
                                  {"run": "up", "read": "down"})
    rw_clean = carrier_rewriters(ast.parse(_ORCH_CLEAN), {"run"}, {"read"},
                                 {"run": "up", "read": "down"})
    checks["k6_rewriter_probe_sees_a_hidden_stage"] = (
        rw_hidden["verdict"] == "measured" and rw_hidden["hidden"] == ["clamp"])
    checks["k7_alias_and_derivative_are_not_rewriters"] = (
        rw_clean["verdict"] == "measured" and rw_clean["sites"] == [])
    od_inv = stage_order(ast.parse(_ORCH_INVERTED), {"a": {"first"}, "b": {"second"}},
                         ("a", "b"))
    od_ok = stage_order(ast.parse(_ORCH_ORDERED), {"a": {"first"}, "b": {"second"}},
                        ("a", "b"))
    checks["k8_order_probe_sees_an_inversion"] = (
        od_inv["verdict"] == "measured" and od_inv["inversions"] == [["a", "b"]])
    checks["k9_owner_order_gives_zero_and_early_exit_is_off_path"] = (
        od_ok["verdict"] == "measured" and od_ok["inversions"] == []
        and od_ok["positions"]["b"]["first"][-1] == 8)
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
        rw = e.get("rewriters") or {}
        if rw.get("verdict") == "unmeasured":
            out.append({"severity": "unchecked",
                        "text": f"переписчики носителя «{head}» не измерены: {rw['reason']}"})
        elif rw.get("verdict") == "measured":
            if rw["hidden"]:
                n_sites = sum(1 for s in rw["sites"] if s["kind"] == "hidden")
                rebound = sorted({b for s in rw["sites"] for b in s["bound"]})
                out.append({"severity": "critical",
                            "text": (f"СКРЫТЫЕ СТУПЕНИ на стыке «{head}»: носитель "
                                     f"`{', '.join(rebound)}` между входами "
                                     f"(строки {rw['span'][0]}–{rw['span'][1]} "
                                     f"`{rw['function']}`) пересвязывают "
                                     f"{len(rw['hidden'])} функций, которых в карте "
                                     f"владельца нет, на {n_sites} площадках: "
                                     f"{', '.join(rw['hidden'])}. «Состав 10/10, "
                                     "строить нечего» был о ПРОПИСАННЫХ ступенях")})
            for key in rw["declared_out_of_place"]:
                nm = next((s.owner_name for s in STAGES if s.key == key), key)
                n_sites = sum(1 for s in rw["sites"] if s["stage"] == key)
                out.append({"severity": "warn",
                            "text": (f"прописанная ступень «{nm}» переписывает носитель "
                                     f"стыка «{head}» ({n_sites} площадк(а/и)) — в карте "
                                     "владельца она стои́т не здесь")})
    for rel, od in (meas.get("order") or {}).items():
        if od["verdict"] == "unmeasured":
            out.append({"severity": "unchecked",
                        "text": f"порядок ступеней в {rel} не измерен: {od['reason']}"})
            continue
        if od["inversions"]:
            names = {s.key: s.owner_name for s in STAGES}
            pairs = "; ".join(f"«{names.get(a, a)}» после «{names.get(b, b)}»"
                              for a, b in od["inversions"])
            out.append({"severity": "warn",
                        "text": (f"порядок живого цикла ({rel}, корень `{od['root']}`) "
                                 f"расходится с картой владельца: {len(od['inversions'])} "
                                 f"инверси(я/и) — {pairs}. Мера — первая строка вызова "
                                 "на сквозном пути (прокси)")})
        for key, off in (od.get("off_path") or {}).items():
            names = {s.key: s.owner_name for s in STAGES}
            out.append({"severity": "warn",
                        "text": (f"вход ступени «{names.get(key, key)}» в {rel} зовётся ТОЛЬКО в "
                                 f"ветке раннего выхода (`{off.get('function') or '?'}`, "
                                 f"строка {(off.get('first') or ['?'])[-1]}): на сквозном "
                                 "пути цикла её нет")})
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
    hidden: set[str] = set()
    hidden_sites = 0
    rewriters_unmeasured = 0
    for e in meas["edges"]:
        rw = e.get("rewriters") or {}
        if rw.get("verdict") == "measured":
            hidden |= set(rw["hidden"])
            hidden_sites += sum(1 for s in rw["sites"] if s["kind"] == "hidden")
        elif rw.get("verdict") == "unmeasured":
            rewriters_unmeasured += 1
    inversions = sum(len(od.get("inversions") or []) for od in meas["order"].values()
                     if od["verdict"] == "measured")
    off_path = sum(len(od.get("off_path") or {}) for od in meas["order"].values())
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
        "schema": "cio_component_map/v2",
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
        # Третья ось (ADR-991): скрытые ступени и порядок. Отсутствие измерения
        # у стыка — отдельное число, а не ноль скрытых (инв. #17).
        "hidden_stages": sorted(hidden),
        "hidden_stage_sites": hidden_sites,
        "rewriters_unmeasured_edges": rewriters_unmeasured,
        "stage_order": meas["order"],
        "order_inversions": inversions,
        "stages_off_path": off_path,
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
