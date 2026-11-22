"""foreign_carrier_cadence_census.py — перепись класса «шаг ИЗМЕРЕН с одного
носителя, а вердикт выносится о другом».

# LLM_FORBIDDEN

## Предмет

Находка цикла #1214 (ADR-1071) в общем виде. Перепись §31 приказа «Portfolio CIO»
решала, достижим ли горизонт наблюдения, ОДНИМ скаляром — шагом **дневного
трека** (`equity_curve_daily.json`, 24 ч), — и числила горизонты 1h/6h
невозможными ПО ПОСТРОЕНИЮ. Но counterfactual счита́ется НЕ из трека: он
счита́ется из `apy_evidenced_pct` **журнала решений**, а тот с ADR-395 несёт по
нескольку прогонов в сутки. Шаг был измерен у ЧУЖОГО носителя, и ошибка шла в
успокаивающую сторону: два требования владельца значились невозможными, а были
просто непосчитанными.

Заказ G1058 п. 2 спросил: **сколько ЕЩЁ приборов судят о достижимости или
свежести одного носителя шагом ДРУГОГО.** Нулём это не считалось: закрыта была
одна дверь. Этот модуль — прибор на тот вопрос.

## Почему вопрос НЕ тот же, что у соседей

Рядом живут два прибора о сроках, и ни один на этот вопрос не отвечает:

| прибор | его вопрос | чего НЕ спрашивает |
|---|---|---|
| `monitoring/slo_keepability.py` | держи́м ли ОБЪЯВЛЕННЫЙ срок артефакта при такте его производителя | откуда взялся шаг, если он не объявлен, а ИЗМЕРЕН |
| `monitoring/slo_proposal.py` | какой срок СЛЕДУЕТ из расписания агента | то же самое |
| **этот** | **чей носитель дал шаг, которым выносится вердикт** | держи́м ли срок · верен ли сам шаг |

Оба соседа работают на ОБЪЯВЛЕННОМ пороге (`manifest.json`, константа). Порог
по природе есть **решение** и чужим носителем быть не может — он вообще не
наблюдение (`.claude/rules/site-numbers.md`: «замер устаревает за сутки, порог
не устаревает вовсе»). Класс живёт ровно там, где шаг — **ЗАМЕР**: функция
считает статистику по содержимому носителя, переданного ей аргументом, и
полученное число становится меркой вердикта.

## Четыре рода, и они различимы (инв. #17)

Для каждого сайта вердикта («возраст/горизонт» против «шага») прибор отвечает
одним из четырёх, и ни один не выдаётся за другой:

* `step_declared` — шаг есть **РЕШЕНИЕ** (константа, аргумент CLI, манифест).
  Вопрос о носителе к нему НЕ ПРИМЕНИМ, и членом класса такой сайт не является.
  Это НЕ «чисто» и НЕ «грязно» — это другой вопрос.
* `single_carrier` — шаг ИЗМЕРЕН, и носитель, с которого он снят, —
  **единственный**, который читает функция. Безопасно ПО ПОСТРОЕНИЮ: чужого
  носителя в этой функции нет. Это доказательство, а не замер.
* `foreign_carrier_candidate` — шаг ИЗМЕРЕН с носителя K, а функция читает ещё
  и другие носители. **Предмет класса.** Прибор называет кандидата ПОИМЁННО и
  разрешать его обязан человек: привязать вердикт к носителю величины не может
  никакая синтаксическая мера — это вопрос о СМЫСЛЕ, и прибор говорит это сам.
* `unmeasured` — провенанс не разобран, и причина НАЗВАНА. Не ноль и не «чисто».

**Верхняя граница, а не точное число.** `foreign_carrier_candidate` — именно
КАНДИДАТ: функция, читающая два носителя и мерящая шаг у одного, вправе
выносить вердикт именно о нём. Поэтому прибор отвечает на вопрос «где это
ВОЗМОЖНО», а «где это ТАК» разрешается поимённо, записью. Выдать кандидата за
члена значило бы ровно ту подмену, против которой написан весь этот слой.

## Чего прибор НЕ ДОКЛАДЫВАЕТ

* **верен ли сам шаг.** Медиана, минимум и максимум зазоров — три разных числа
  об одном носителе (замер ADR-1071: 0.006 / 0.546 / 16.4 ч), и выбор между
  ними есть решение, а не синтаксис.
* **исполняется ли сайт.** Достижимость сравнения — отдельный вопрос
  (`monitoring/reachability_of_the_rest.py`), и «дорога есть» здесь не мерится.
* **межмодульный зов.** Провенанс разбирается внутри ОДНОЙ функции: шаг,
  добытый зовом помощника из чужого модуля, прибор числит `unmeasured` с
  названной причиной, а не «чисто». Это та же граница, о которую споткнулся
  сторож претензии `injected-clock` (`.claude/rules/deployment.md` § IX).
* **контейнер привязкой НЕ является.** `rows[h] = {"cadence_hours": cadence}`
  не делает `rows` шагом. Отображения-литералы обрывают провенанс намеренно:
  считать «RHS содержит имя» происхождением значило бы оправдать аварию
  2026-08-04 (то же правило, § «Время в тестах»).

## Как звать

    python3 -m spa_core.analytics.foreign_carrier_cadence_census [--repo-root <дерево>]

Дерево — **ВХОД**, умолчание ПЕЧАТАЕТСЯ (ADR-933). Коды возврата:
**0** — измерено, кандидатов нет · **1** — кандидаты НАЗВАНЫ · **2** — НЕ
ИЗМЕРЕНО с названной причиной. Прибор только ЧИТАЕТ: ни одного файла он не
пишет.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

_REPO = Path(__file__).resolve().parents[2]

#: Каталоги поверхности. Тесты исключены намеренно: предмет класса — ПРИБОР,
#: выносящий вердикт о мире, а не сцена, его проверяющая.
SCAN_DIRS: Tuple[str, ...] = ("spa_core", "scripts")

#: Роды исхода. Порядок — порядок печати; состав ЗАМКНУТ (сторож сверяет с ним).
KINDS: Tuple[str, ...] = ("foreign_carrier_candidate", "single_carrier",
                          "step_declared", "unmeasured")

CLASS_SUBJECT = "foreign_carrier_candidate"

#: Имя, по которому функция ПРЕТЕНДУЕТ быть меркой шага наблюдения.
_STEP_NAME = re.compile(r"cadence|tact|takt|_step_hours|step_hours|observation_step"
                        r"|interval_hours|_shag|gap_hours", re.I)

#: Статистики, которыми шаг СЧИТАЮТ по содержимому носителя. Присутствие любой
#: из них в теле функции и есть признак «шаг ИЗМЕРЕН, а не объявлен».
_STAT_NAMES: FrozenSet[str] = frozenset({
    "min", "max", "median", "mean", "fmean", "quantiles", "pstdev", "stdev",
})

#: Имена-мешки носителей: `carriers.get("daily")`, `docs["eval"]`, …
_CARRIER_BAGS: FrozenSet[str] = frozenset({
    "carriers", "docs", "inputs", "sources", "feeds", "books", "journals",
    "artifacts", "payloads", "rows_by", "loaded",
})

#: Величина, о которой выносится вердикт свежести/достижимости.
_QUANTITY = re.compile(r"\bage\b|age_|_age|\bgap|elapsed|since_|_since|\blag\b"
                       r"|horizon|\bhh\b|hours_old|staleness", re.I)

#: Операторы вердикта. `==`/`!=` сюда не входят: равенство срока — не вердикт
#: о свежести, а сверка.
_CMP_OPS = (ast.Gt, ast.GtE, ast.Lt, ast.LtE)


# ───────────────────────────── носитель ──────────────────────────────────────

def carrier_token(node: ast.AST) -> Optional[str]:
    """Имя НОСИТЕЛЯ, если это выражение его называет, иначе ``None``.

    Три формы, и каждая названа:

    * ``carriers.get("daily")`` / ``docs["eval"]`` — мешок носителей, токен
      ``bag:<ключ>``. Имя мешка обязано быть из :data:`_CARRIER_BAGS`: иначе
      любой ``cfg.get("x")`` числился бы носителем.
    * строковый литерал пути данных (``data/…``, ``*.json``, ``*.jsonl``) —
      токен ``path:<значение>``.
    * ничего из этого — ``None``, и это «не разобрали», а не «носителя нет».
    """
    if isinstance(node, ast.Call):
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "get"
                and isinstance(fn.value, ast.Name) and fn.value.id in _CARRIER_BAGS
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            return f"bag:{node.args[0].value}"
        return None
    if isinstance(node, ast.Subscript):
        val, sl = node.value, node.slice
        if (isinstance(val, ast.Name) and val.id in _CARRIER_BAGS
                and isinstance(sl, ast.Constant) and isinstance(sl.value, str)):
            return f"bag:{sl.value}"
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        v = node.value
        if v.startswith("data/") or v.endswith(".json") or v.endswith(".jsonl"):
            return f"path:{v}"
    return None


def carriers_of(node: ast.AST) -> Set[str]:
    """Все носители, названные ВНУТРИ выражения или тела."""
    found: Set[str] = set()
    for sub in ast.walk(node):
        tok = carrier_token(sub)
        if tok:
            found.add(tok)
    return found


# ───────────────────────── шаг: ИЗМЕРЕН или ОБЪЯВЛЕН ─────────────────────────

def _statistic_over_a_collection(call: ast.Call) -> Optional[str]:
    """Имя статистики, если зов СЧИТАЕТ её по КОЛЛЕКЦИИ, иначе ``None``.

    🪤 **Зажим статистикой не является, и это стоило замера.** Первая редакция
    спрашивала только «встречается ли ``min``/``max`` в теле», и зачла шестерых
    чужих: ``max(int(m.group(1)) / 3600.0, 0.0834)`` в
    `monitoring/slo_proposal.cadence_hours` — это ПОЛ («не мельче пяти минут»),
    а не замер по носителю. Замер отличает от зажима ровно ЧИСЛО аргументов:
    ``min(gaps)`` — один аргумент-коллекция, ``max(x, floor)`` — два скаляра.
    """
    fn = call.func
    name = (fn.id if isinstance(fn, ast.Name) else
            fn.attr if isinstance(fn, ast.Attribute) else None)
    if name not in _STAT_NAMES:
        return None
    if len(call.args) != 1 or call.keywords:
        return None
    if isinstance(call.args[0], ast.Starred):
        return None
    return name


def measured_step_functions(tree: ast.Module) -> Dict[str, Dict[str, Any]]:
    """Функции модуля, чей результат есть ШАГ, **ИЗМЕРЕННЫЙ** по содержимому.

    Два условия, и оба обязательны:

    1. имя ПРЕТЕНДУЕТ быть меркой шага (:data:`_STEP_NAME`);
    2. тело СЧИТАЕТ статистику **по коллекции**
       (:func:`_statistic_over_a_collection`) — то есть число выводится из
       содержимого, а не возвращается из объявления и не зажимается полом.

    Одного имени НЕ ДОСТАТОЧНО намеренно: ``def cadence_hours(schedule)``
    (`monitoring/slo_proposal.py`) разбирает ОБЪЯВЛЕННОЕ расписание и шага ни
    по какому носителю не мерит — числить его замером значило бы приписать
    классу чужого.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _STEP_NAME.search(node.name):
            continue
        stats = sorted({s for s in (
            _statistic_over_a_collection(sub) for sub in ast.walk(node)
            if isinstance(sub, ast.Call)) if s})
        if not stats:
            continue
        params = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
        out[node.name] = {"line": node.lineno, "statistics": stats, "params": params}
    return out


# ───────────────────────────── провенанс ─────────────────────────────────────

def provenance(func: ast.AST) -> Dict[str, Set[str]]:
    """Происхождение каждого локального имени функции — до неподвижной точки.

    Токены: ``call:<имя>`` · ``carrier:<токен>`` · ``name:<имя>`` ·
    ``container`` · ``const`` · ``global`` .

    **Отображение-литерал обрывает цепь.** `RHS` вида ``{...}`` / ``[...]`` даёт
    ``container`` и внутренних имён НЕ распространяет: «RHS содержит имя» не
    есть происхождение значения (тот же урок, что у сторожа `injected-clock`).
    """
    raw: Dict[str, Set[str]] = {}

    def origins(rhs: ast.AST) -> Set[str]:
        if isinstance(rhs, (ast.Dict, ast.List, ast.Set, ast.DictComp,
                            ast.ListComp, ast.SetComp)):
            return {"container"}
        toks: Set[str] = set()
        for sub in ast.walk(rhs):
            tok = carrier_token(sub)
            if tok:
                toks.add(f"carrier:{tok}")
                continue
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Name):
                    toks.add(f"call:{sub.func.id}")
                elif isinstance(sub.func, ast.Attribute):
                    toks.add(f"call:{sub.func.attr}")
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                toks.add("global" if sub.id.isupper() else f"name:{sub.id}")
            elif isinstance(sub, ast.Constant):
                toks.add("const")
        return toks

    def bind(target: ast.AST, toks: Set[str]) -> None:
        if isinstance(target, ast.Name):
            raw.setdefault(target.id, set()).update(toks)
        elif isinstance(target, (ast.Tuple, ast.List)):
            # `cadence, why = _cadence_hours(x)` — распаковка связывает ОБА имени
            for elt in target.elts:
                bind(elt, toks)

    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            toks = origins(node.value)
            for tgt in node.targets:
                bind(tgt, toks)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            bind(node.target, origins(node.value))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bind(node.target, {"container"})
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            bind(node.optional_vars, origins(node.context_expr))

    # неподвижная точка по `name:` — ровно как у разборщика претензии часов
    resolved: Dict[str, Set[str]] = {k: set(v) for k, v in raw.items()}
    for _ in range(len(resolved) + 2):
        changed = False
        for key, toks in resolved.items():
            for tok in [t for t in toks if t.startswith("name:")]:
                other = tok.split(":", 1)[1]
                if other == key:
                    continue
                add = resolved.get(other, set()) - toks
                if add:
                    toks |= add
                    changed = True
        if not changed:
            break
    return resolved


def _step_calls_of(name: str, prov: Dict[str, Set[str]],
                   steps: Dict[str, Dict[str, Any]]) -> Set[str]:
    """Мерки шага, до которых доходит провенанс имени ``name``."""
    toks = prov.get(name, set())
    return {t.split(":", 1)[1] for t in toks
            if t.startswith("call:") and t.split(":", 1)[1] in steps}


def _step_carrier(func: ast.AST, step_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Носитель, С КОТОРОГО снят шаг: разбор АРГУМЕНТОВ зова мерки.

    Возвращает ``(токен, причина_если_нет)``. Два зова одной мерки с РАЗНЫХ
    носителей — честное «не измерено»: какой из них дал число вердикту, синтаксис
    не говорит.
    """
    seen: Set[str] = set()
    calls = 0
    for sub in ast.walk(func):
        if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id == step_name):
            continue
        calls += 1
        for arg in list(sub.args) + [kw.value for kw in sub.keywords]:
            seen |= carriers_of(arg)
    if not calls:
        return None, f"зов мерки {step_name}() в функции не найден"
    if not seen:
        return None, f"аргумент мерки {step_name}() носителя не называет"
    if len(seen) > 1:
        return None, (f"мерка {step_name}() зовётся с РАЗНЫХ носителей "
                      f"({', '.join(sorted(seen))}) — какой дал число вердикту, "
                      f"синтаксис не говорит")
    return next(iter(seen)), None


# ───────────────────────────── сайты вердикта ────────────────────────────────

def _looks_like_quantity(text: str) -> bool:
    return bool(_QUANTITY.search(text))


def _looks_like_step(text: str) -> bool:
    return bool(_STEP_NAME.search(text)) or bool(
        re.search(r"threshold|limit|porog|max_age|ttl|budget|slo|window", text, re.I))


def census_module(rel: str, text: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Сайты вердикта одного модуля. Второй член — причина, если НЕ РАЗОБРАН."""
    sites, why, _ = census_module_full(rel, text)
    return sites, why


def census_module_full(rel: str, text: str
                       ) -> Tuple[List[Dict[str, Any]], Optional[str],
                                  Dict[str, Dict[str, Any]]]:
    """То же, но третьим членом — ЗНАМЕНАТЕЛЬ модуля: его мерки шага.

    Знаменатель печатается рядом с ответом НАМЕРЕННО: «кандидатов 0» при двух
    мерках шага в дереве и «кандидатов 0» при двухстах — утверждения разной
    силы, и умолчать знаменатель значило бы выдать второе за первое.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"{rel}: не разбирается — {exc}", {}
    steps = measured_step_functions(tree)
    sites: List[Dict[str, Any]] = []

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        prov = provenance(func)
        fn_carriers = sorted(carriers_of(func))
        for node in ast.walk(func):
            if not isinstance(node, ast.Compare) or len(node.ops) != 1:
                continue
            if not isinstance(node.ops[0], _CMP_OPS):
                continue
            left, right = node.left, node.comparators[0]
            lt, rt = ast.unparse(left), ast.unparse(right)

            def measured_side(side: ast.AST) -> Set[str]:
                if isinstance(side, ast.Call) and isinstance(side.func, ast.Name) \
                        and side.func.id in steps:
                    return {side.func.id}
                if isinstance(side, ast.Name):
                    return _step_calls_of(side.id, prov, steps)
                found: Set[str] = set()
                for sub in ast.walk(side):
                    if isinstance(sub, ast.Name):
                        found |= _step_calls_of(sub.id, prov, steps)
                    elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                            and sub.func.id in steps:
                        found.add(sub.func.id)
                return found

            l_steps, r_steps = measured_side(left), measured_side(right)
            quantity_vs_step = ((_looks_like_quantity(lt) and _looks_like_step(rt))
                                or (_looks_like_quantity(rt) and _looks_like_step(lt)))

            base = {"module": rel, "line": node.lineno, "function": func.name,
                    "expression": f"{lt} {type(node.ops[0]).__name__} {rt}"[:200],
                    "function_carriers": fn_carriers}

            if l_steps and r_steps:
                sites.append({**base, "kind": "unmeasured",
                              "reason": "мерка ИЗМЕРЕННОГО шага с ОБЕИХ сторон — "
                                        "о чём вердикт, синтаксис не говорит"})
                continue
            measured = l_steps or r_steps
            if not measured:
                if quantity_vs_step:
                    sites.append({**base, "kind": "step_declared",
                                  "reason": "шаг не ИЗМЕРЕН по носителю — это "
                                            "объявленный порог (решение)"})
                continue
            if len(measured) > 1:
                sites.append({**base, "kind": "unmeasured",
                              "reason": f"до операнда доходят РАЗНЫЕ мерки шага "
                                        f"({', '.join(sorted(measured))})"})
                continue
            step_name = next(iter(measured))
            tok, why = _step_carrier(func, step_name)
            row = {**base, "step": step_name, "step_carrier": tok}
            if tok is None:
                row.update({"kind": "unmeasured", "reason": why})
            elif len(fn_carriers) <= 1:
                row.update({"kind": "single_carrier",
                            "reason": "шаг снят с ЕДИНСТВЕННОГО носителя функции — "
                                      "чужого здесь нет ПО ПОСТРОЕНИЮ"})
            else:
                others = [c for c in fn_carriers if c != tok]
                row.update({"kind": CLASS_SUBJECT, "other_carriers": others,
                            "reason": (f"шаг ИЗМЕРЕН с «{tok}», а функция читает ещё "
                                       f"{len(others)}: {', '.join(others)} — вердикт "
                                       f"к носителю шага синтаксисом не привязан")})
            sites.append(row)
    return sites, None, steps


def container_crossings(rel: str, text: str) -> List[Dict[str, Any]]:
    """Где ИЗМЕРЕННЫЙ шаг укладывается в КОНТЕЙНЕР и провенанс обрывается.

    Это НАЗВАННАЯ слепота прибора, а не его ответ. Провенанс намеренно не
    ходит через отображения (`.claude/rules/deployment.md` § «Время в тестах»:
    считать «RHS содержит имя» происхождением значило бы оправдать аварию
    2026-08-04). Цена этого выбора — ИЗМЕРИМА: значение шага, положенное в
    словарь и вынутое в другой функции, прибор как шаг больше не видит.

    Замер 2026-11-22 нашёл ровно один переход (`sensor_tact_census`:
    ``entry["tact_hours"] = tact``), и он ЗАКОНЕН: по ту сторону контейнера
    такт артефакта сравнивается с ОБЪЯВЛЕННЫМ сроком ТОГО ЖЕ артефакта — один
    носитель, не чужой. Но узнать это можно только прочитав, и потому переход
    ПЕЧАТАЕТСЯ, а не замалчивается.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    steps = measured_step_functions(tree)
    if not steps:
        return []
    out: List[Dict[str, Any]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        prov = provenance(func)
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, (ast.Subscript, ast.Attribute))
                       for t in node.targets):
                continue
            reached: Set[str] = set()
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Name):
                    reached |= _step_calls_of(sub.id, prov, steps)
                elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                        and sub.func.id in steps:
                    reached.add(sub.func.id)
            if reached:
                out.append({"module": rel, "line": node.lineno,
                            "function": func.name,
                            "steps": sorted(reached),
                            "expression": ast.unparse(node)[:160]})
    return out


def exported_steps(repo_root: Path, denominator: Sequence[Dict[str, Any]],
                   files: Sequence[Path]) -> List[Dict[str, Any]]:
    """Мерки шага, которые зовёт ЧУЖОЙ модуль — вторая названная слепота.

    Провенанс разбирается внутри одного модуля, поэтому шаг, измеренный в
    модуле A и применённый в модуле B, прибор бы не связал. Вопрос задаётся
    ОТДЕЛЬНО и отвечается ЧИСЛОМ: у каждой мерки считаются ЗОВЫ вне её модуля.

    🪤 **Зов считается по AST, а не грепом, и это стоило ложного срабатывания
    в собственном приборе.** Первая редакция искала ``имя(`` регулярным
    выражением по сырому тексту и зачла чужим зовом КОММЕНТАРИЙ этого самого
    модуля (строка «``cadence, why = _cadence_hours(x)`` — распаковка связывает
    ОБА имени»): ответ «1 из 3» был неверен, и неверен в сторону находки.
    Класс известен и уже сторожится рядом
    (`spa_core/tests/test_unwired_comment_is_not_a_caller.py`: проза зовом не
    является), а «упомянут» ≠ «зовёт» — дословно ADR-1028. ``ast.Call`` прозы
    не видит ПО ПОСТРОЕНИЮ.
    """
    out: List[Dict[str, Any]] = []
    calls_by_name: Dict[str, List[str]] = {}
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for sub in ast.walk(tree):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            name = (fn.id if isinstance(fn, ast.Name) else
                    fn.attr if isinstance(fn, ast.Attribute) else None)
            if name:
                calls_by_name.setdefault(name, []).append(f"{rel}:{sub.lineno}")
    for step in denominator:
        callers = [c for c in calls_by_name.get(step["step"], [])
                   if c.rsplit(":", 1)[0] != step["module"]]
        out.append({**{k: step[k] for k in ("module", "step", "line")},
                    "foreign_callers": sorted(callers)})
    return out


# ───────────────────────────── перепись ──────────────────────────────────────

def census(repo_root: Path, scan_dirs: Sequence[str] = SCAN_DIRS) -> Dict[str, Any]:
    """Перепись дерева. ``measured=False`` — третий исход с названной причиной."""
    if not repo_root.is_dir():
        return {"measured": False, "reason": f"дерево не читается: {repo_root}",
                "repo_root": str(repo_root)}
    files: List[Path] = []
    missing = [d for d in scan_dirs if not (repo_root / d).is_dir()]
    for d in scan_dirs:
        files.extend(sorted((repo_root / d).rglob("*.py")))
    files = [p for p in files
             if "/tests/" not in p.as_posix() and not p.name.startswith("test_")]
    if not files:
        return {"measured": False, "repo_root": str(repo_root),
                "reason": (f"ни одного модуля в {', '.join(scan_dirs)} — "
                           f"нечитаемые каталоги: {missing or 'нет'}")}

    sites: List[Dict[str, Any]] = []
    unparsed: List[str] = []
    denominator: List[Dict[str, Any]] = []
    crossings: List[Dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unparsed.append(f"{rel}: не прочитан — {exc}")
            continue
        got, why, steps = census_module_full(rel, text)
        if why:
            unparsed.append(why)
        sites.extend(got)
        crossings.extend(container_crossings(rel, text))
        for name, meta in sorted(steps.items()):
            denominator.append({"module": rel, "step": name, "line": meta["line"],
                                "statistics": meta["statistics"],
                                "params": meta["params"]})

    tally = {k: sum(1 for s in sites if s["kind"] == k) for k in KINDS}
    return {"measured": True, "repo_root": str(repo_root),
            "scan_dirs": list(scan_dirs), "modules_read": len(files),
            "missing_dirs": missing, "unparsed": unparsed,
            "sites": sites, "tally": tally,
            "measured_steps": denominator,
            "container_crossings": crossings,
            "exported_steps": exported_steps(repo_root, denominator, files),
            "subjects": [s for s in sites if s["kind"] == CLASS_SUBJECT]}


def format_report(doc: Dict[str, Any]) -> str:
    """Человеческий отчёт. Третий исход печатается ПРИЧИНОЙ, а не нулём."""
    if not doc.get("measured"):
        return ("НЕ ИЗМЕРЕНО: класс «шаг с чужого носителя» не мерен — "
                f"{doc.get('reason')}")
    t = doc["tally"]
    out = [
        "Класс «шаг ИЗМЕРЕН с одного носителя, а вердикт выносится о другом» "
        f"(обобщение ADR-1071)",
        f"  дерево: {doc['repo_root']}  ·  модулей прочитано: {doc['modules_read']}"
        f"  ·  каталоги: {', '.join(doc['scan_dirs'])}",
        f"  ПРЕДМЕТ КЛАССА (кандидаты): {t[CLASS_SUBJECT]}",
        f"  безопасно ПО ПОСТРОЕНИЮ (единственный носитель): {t['single_carrier']}",
        f"  шаг — РЕШЕНИЕ, вопрос не применим: {t['step_declared']}",
        f"  НЕ ИЗМЕРЕНО: {t['unmeasured']}",
        f"  ЗНАМЕНАТЕЛЬ — мерок шага, ИЗМЕРЯЮЩИХ статистику по коллекции: "
        f"{len(doc.get('measured_steps') or [])}",
    ]
    for d in doc.get("measured_steps") or []:
        out.append(f"     · {d['module']}:{d['line']} {d['step']}()  "
                   f"стат={','.join(d['statistics'])}  арг={','.join(d['params'])}")
    for s in doc["subjects"]:
        out.append(f"  ⚠️  {s['module']}:{s['line']} {s['function']}() — {s['reason']}")
        out.append(f"        {s['expression']}")
    exported = doc.get("exported_steps") or []
    foreign = [e for e in exported if e["foreign_callers"]]
    out.append(f"  СЛЕПОТА 1 (межмодульный зов) ИЗМЕРЕНА: мерок, которые зовёт "
               f"ЧУЖОЙ модуль — {len(foreign)} из {len(exported)}")
    for e in foreign:
        out.append(f"     · {e['module']}:{e['line']} {e['step']}() ← "
                   f"{', '.join(e['foreign_callers'][:6])}")
    crossings = doc.get("container_crossings") or []
    out.append(f"  СЛЕПОТА 2 (шаг уложен в КОНТЕЙНЕР, провенанс обрывается "
               f"намеренно) ИЗМЕРЕНА: переходов {len(crossings)}")
    for c in crossings:
        out.append(f"     · {c['module']}:{c['line']} {c['function']}() "
                   f"[{','.join(c['steps'])}]  {c['expression']}")
    if doc["unparsed"]:
        out.append(f"  НЕ РАЗОБРАНО файлов: {len(doc['unparsed'])}")
        for why in doc["unparsed"][:10]:
            out.append(f"     · {why}")
    out.append("  ПРЕДМЕТ — именно КАНДИДАТ: привязать вердикт к носителю величины "
               "синтаксис не может, это вопрос о СМЫСЛЕ и разрешается записью")
    out.append("  НЕ ДОКЛАДЫВАЕТ: верен ли сам шаг · исполняется ли сайт · "
               "законен ли переход через контейнер (это читают, а не выводят)")
    out.append("  ADVISORY: прибор только ЧИТАЕТ — ни одного файла не пишет")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="дерево, о котором выносится вердикт; умолчание ПЕЧАТАЕТСЯ")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ns = ap.parse_args(argv)

    if ns.repo_root is None:
        root = _REPO
        if not ns.json:
            print(f"дерево НЕ НАЗВАНО входом --repo-root — отвечаю о своём: {root}")
    else:
        root = Path(ns.repo_root).expanduser().resolve()

    doc = census(root)
    print(json.dumps(doc, ensure_ascii=False, indent=1) if ns.json
          else format_report(doc))
    if not doc.get("measured"):
        return 2
    return 1 if doc["tally"][CLASS_SUBJECT] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
