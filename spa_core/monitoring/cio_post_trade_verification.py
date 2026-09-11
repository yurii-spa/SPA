"""§5 ТЗ «Portfolio CIO» — последняя ступень цепи: post-trade verification.

Заказ цикла #516 дословно: открытый остаток самого ТЗ (не приёмки) — §5 «As-Is
Investigation», последняя неотвеченная ступень цепочки ``execution planning →
execution → post-trade verification``. §46 (ADR-253) измерил, что стык
«Post-Trade Monitor → Reporting» это РАЗРЫВ (``execution_reconciliation.json``
не получает никто), но **ЧТО именно пишется в этот артефакт и соответствует ли
оно исполненному — не мерил никто.**

Заказ назвал и ловушку заранее: система в paper-режиме, «исполнения» в смысле
сделки нет вовсе, поэтому первый вопрос — **есть ли предмет замера сегодня**, и
честный ответ «предмета нет» является полным ответом. Мерить надо наличие
ВХОДА, а не строить сверку того, чего не происходит.

## Ловушка сработала не в ту сторону, и это пришлось измерить, а не предположить

«Исполнения нет» — гипотеза, а не факт, и у слова «исполнение» здесь ДВА
смысла, которые дают противоположные ответы:

* **on-chain** — сделки нет ни одной, и это не наблюдение, а устройство:
  ``execution/router.py`` держит режим-заглушку, ``execution/draft_prep.py``
  требует подписи ЧЕЛОВЕКА (§46 объявил обе ступени родом ``human``).
* **ход бумажной книги** — за трек их 32, все ``is_demo=False``, и книга после
  каждого реально другая.

Ступень, о которой спрашивает заказ, построена под ВТОРОЙ смысл: её модуль
``execution/reconciliation.py`` в собственной шапке объявляет себя
«DRY-RUN / virtual ledger ONLY» и сверяет ``plan_trades → dry_run_execute →
reconcile``. Значит **предмет замера есть**, и ответ «предмета нет» был бы
уверенным неверным ответом — тем самым, которым прибор ошибался четыре раза в
#516 и пять раз в #515.

Поэтому смысл здесь ОБЪЯВЛЕН данными (``SUBJECT_SENSES``), а не выведен из
слова: замер называет оба и говорит, какой из них ступень верифицирует.

## Что меряется

Три вопроса, и они разные — зелёный ответ на один не отвечает на два других:

1. **Есть ли предмет** (``measure_subject``) — сколько ходов книги произошло и
   когда последний. Источник — ``data/trades.json`` (не-demo записи) и книга
   ``data/current_positions.json``.
2. **Подаётся ли ступени исполненное** (``measure_inputs``) — ГЛАВНЫЙ вопрос.
   У сверки «намерение против результата» два аргумента, и всё решает
   происхождение ВТОРОГО: если ``resulting`` получен из ``target`` в том же
   вызове, сверка сравнивает величину с самой собой, и расхождение недостижимо
   ПО ПОСТРОЕНИЮ. Меряется разбором (AST) с прослеживанием происхождения до
   неподвижной точки — не грепом и не по имени переменной.
3. **Соответствует ли содержимое исполненному** (``measure_content``) — книга
   в артефакте против сегодняшней книги: какие позиции исчезли, какие
   появились, сходятся ли суммы, сколько ходов произошло ПОСЛЕ отметки
   артефакта.

## Чем это НЕ является

Это не «сторож протухания». Возраст артефакта сам по себе находкой не является
и не может ею быть: если ходов книги не было, старый артефакт — верное
состояние. Поэтому вопрос 3 гейтится вопросом 1, и обратная половина
положительного контроля проверяет именно это (пустой трек ⇒ находки нет).

И это не «сверка сломана». Сверка как раз рабочая: ``cutover_scorecard``
подаёт ей испорченную копию и доказывает, что расхождение ловится. Находка в
другом — **ей никогда не задают её вопрос о реальности**.

ADVISORY. Модуль ничего не соединяет и не чинит: подать ступени фактический
исход значит изменить путь, на котором принимается решение о капитале, — это
money-path и решение владельца, а не строка автокарточки.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.utils.observation import observed, observed_number

REPORT_REL = "data/cio_post_trade_verification.json"

#: Ключ ступени в карте §46. Состав ступеней НЕ дублируется — берётся из
#: `cio_component_map.STAGES` (прямая инструкция владельца в §3 ТЗ: «не
#: создавать параллельные модели, если такие механизмы уже существуют»).
#: Ключа нет ⇒ громкий UNCHECKED, а не своя копия таблицы.
STAGE_KEY = "post_trade_monitor"

#: ДВА смысла слова «исполнение». Объявлены данными: вывести смысл из слова
#: нельзя, а ответы у них противоположные (см. шапку).
SUBJECT_SENSES: dict[str, dict[str, str]] = {
    "onchain": {
        "what": "подписанная транзакция в сети",
        "why_absent": ("ступени `execution_planner` и `execution_agent` §46 "
                       "объявлены родом human: черновик подписывает человек "
                       "(draft_prep), маршрутизатор держит режим-заглушку "
                       "(router). Это устройство, а не наблюдение"),
    },
    "paper_book": {
        "what": "ход бумажной книги (виртуальный реестр)",
        "why_absent": "",
    },
}

#: Какой смысл верифицирует ступень. ОБЪЯВЛЕНО, а не выведено из шапки модуля:
#: разбор прозы дал бы уверенный ответ там, где нужен контракт.
STAGE_VERIFIES_SENSE = "paper_book"

#: Книга и журнал ходов.
TRADES_REL = "data/trades.json"
BOOK_REL = "data/current_positions.json"


class Reconciler:
    """Объявленная точка сверки «намерение против результата».

    ``target_pos`` / ``resulting_pos`` — позиционные индексы аргументов.
    Контракт ОБЪЯВЛЯЮТ, а не выводят из имён: у одноимённых функций дерева
    (`monitoring/slo_proposal.reconcile`, `analytics/daily_pnl_reconciler`)
    смысл другой, и совпадение имени приняло бы их за предмет замера.
    """

    __slots__ = ("module", "func", "target_pos", "resulting_pos", "why")

    def __init__(self, module: str, func: str, target_pos: int,
                 resulting_pos: int, why: str) -> None:
        self.module = module
        self.func = func
        self.target_pos = target_pos
        self.resulting_pos = resulting_pos
        self.why = why


#: Обе реализации одной и той же сверки. Их ДВЕ, и это не дубль по недосмотру:
#: инвариант #6 запрещает paper-коду импортировать `execution/`, поэтому у
#: бумажного пути своя копия. Мерить надо ОБЕ — замер одной поверхности дал бы
#: верный ответ на не тот вопрос.
RECONCILERS: tuple[Reconciler, ...] = (
    Reconciler("spa_core/execution/reconciliation.py", "reconcile", 0, 1,
               "продукт ступени `post_trade_monitor` §46 пишет именно она"),
    Reconciler("spa_core/paper_trading/pre_cutover_gate.py", "nav_reconcile", 0, 1,
               "та же сверка в бумажном домене (инвариант #6 запрещает "
               "импорт execution/ из paper-пути)"),
)

#: Происхождение второго аргумента.
PROV_SELF = "DERIVED_FROM_TARGET"      #: получен из первого аргумента того же вызова
PROV_LITERAL = "LITERAL"               #: литерал прямо в вызове
PROV_OBSERVED = "OBSERVED"             #: получен из наблюдения книги
PROV_UNCHECKED = "UNCHECKED"           #: разобрать не вышло — третий исход

#: Имена, означающие ЧТЕНИЕ наблюдения (файл/книга), а не вычисление из цели.
#: Объявлены данными по той же причине, что и полярность порогов в #516.
_OBSERVATION_CALLS = frozenset({
    "load_positions", "read_positions", "current_positions", "load_book",
    "read_book", "load", "json_load", "read_json", "load_json",
})
_OBSERVATION_NAMES = frozenset({
    "current_positions", "book", "observed", "observed_positions",
    "actual", "actual_positions", "live_positions",
})


# ─────────────────────────── происхождение значения ──────────────────────────

def _call_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _atoms(node: ast.AST) -> set[tuple[str, str]]:
    """Атомы происхождения под узлом.

    Тот же приём, что в `cio_component_map._atoms`: имя, строка и ИМЯ ВЫЗОВА
    считаются атомами. Спуск в контейнеры здесь РАЗРЕШЁН намеренно и отличается
    от #515: там вопрос был «кто пишет этот файл», и элемент словаря писателем
    не делает; здесь вопрос «из чего собрана величина», и `{**target}` —
    ровно происхождение от target. Разные вопросы, разные правила спуска.
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
        stack.extend(ast.iter_child_nodes(cur))
    return out


def _assignments(fn: ast.AST) -> dict[str, list[ast.AST]]:
    """Присваивания имён внутри функции: имя → список правых частей."""
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(fn):
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out.setdefault(t.id, []).append(value)
            elif isinstance(t, (ast.Tuple, ast.List)):
                for el in t.elts:
                    if isinstance(el, ast.Name):
                        out.setdefault(el.id, []).append(value)
    return out


def _origin(node: ast.AST, assigns: dict[str, list[ast.AST]],
            *, limit: int = 12) -> set[tuple[str, str]]:
    """Атомы происхождения, прослеженные ДО НЕПОДВИЖНОЙ ТОЧКИ.

    Имя, чьё значение присвоено в той же функции, раскрывается в атомы своей
    правой части, и так пока множество растёт. Без этого `resulting =
    exec_res["resulting_positions"]` выглядело бы независимым от `target`,
    хотя ``exec_res`` там же собран из него: происхождение живёт на цепочке
    из трёх присваиваний, а не в одном узле.
    """
    seen: set[tuple[str, str]] = set(_atoms(node))
    for _ in range(limit):
        grown = set(seen)
        for kind, name in list(seen):
            if kind != "n":
                continue
            for rhs in assigns.get(name, []):
                grown |= _atoms(rhs)
        if grown == seen:
            break
        seen = grown
    return seen


def classify_resulting(call: ast.Call, rec: Reconciler,
                       assigns: dict[str, list[ast.AST]]) -> dict[str, Any]:
    """Откуда взялся второй аргумент сверки.

    Порядок разбора — от самого сильного признака к самому слабому, и
    «не разобрал» является ТРЕТЬИМ ИСХОДОМ, а не молчаливым пропуском.
    """
    args = list(call.args)
    if len(args) <= max(rec.target_pos, rec.resulting_pos):
        return {"provenance": PROV_UNCHECKED,
                "detail": (f"вызов даёт {len(args)} позиционных аргумент(а/ов), "
                           f"а сверке нужен аргумент №{rec.resulting_pos + 1} — "
                           "разобрать нечего")}
    target_node = args[rec.target_pos]
    res_node = args[rec.resulting_pos]

    target_atoms = _origin(target_node, assigns)
    res_atoms = _origin(res_node, assigns)

    # Литерал прямо в вызове: словарь без единого имени и вызова.
    if isinstance(res_node, ast.Dict) and not any(k == "n" for k, _ in res_atoms):
        return {"provenance": PROV_LITERAL,
                "detail": "второй аргумент — словарь-литерал прямо в вызове"}

    shared = {a for a in (target_atoms & res_atoms) if a[0] == "n"}
    if shared:
        return {"provenance": PROV_SELF,
                "detail": ("второй аргумент происходит от первого: общее "
                           f"происхождение {sorted(n for _, n in shared)}")}

    observed = ({n for k, n in res_atoms if k == "f" and n in _OBSERVATION_CALLS}
                | {n for k, n in res_atoms if k == "n" and n in _OBSERVATION_NAMES})
    if observed:
        return {"provenance": PROV_OBSERVED,
                "detail": f"второй аргумент получен наблюдением: {sorted(observed)}"}

    return {"provenance": PROV_UNCHECKED,
            "detail": ("происхождение второго аргумента не разобрано "
                       f"(атомы: {sorted(n for _, n in res_atoms)[:6]})")}


# ─────────────────────────────── замеры ──────────────────────────────────────

def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "файла нет"
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def measure_subject(root: Path) -> dict[str, Any]:
    """Вопрос 1: есть ли что верифицировать.

    ``NO_SUBJECT`` — полный и честный ответ, а не отказ: он гейтит вопрос 3.
    """
    trades, err = _read_json(root / TRADES_REL)
    if err is not None:
        return {"verdict": PROV_UNCHECKED, "reason": f"{TRADES_REL}: {err}",
                "moves": 0, "senses": SUBJECT_SENSES,
                "verifies_sense": STAGE_VERIFIES_SENSE}
    if isinstance(trades, dict):
        trades = trades.get("trades") or []
    if not isinstance(trades, list):
        return {"verdict": PROV_UNCHECKED,
                "reason": f"{TRADES_REL}: ожидался список, получен "
                          f"{type(trades).__name__}",
                "moves": 0, "senses": SUBJECT_SENSES,
                "verifies_sense": STAGE_VERIFIES_SENSE}

    real: list[dict[str, Any]] = []
    demo = 0
    for t in trades:
        if not isinstance(t, dict):
            continue
        if t.get("is_demo"):
            demo += 1
            continue
        real.append(t)

    stamps = sorted(d for d in (_parse_ts(t.get("ts")) for t in real) if d)
    gross = 0.0
    trades_without_diff = 0
    for t in real:
        diff = observed_number(t, "diff_usd")
        if diff is None:
            # Сделка без суммы не «нулевая»: её просто не записали. Ноль занизил
            # бы валовой оборот, по которому судят пост-трейд контроль.
            trades_without_diff += 1
            continue
        gross += abs(diff)

    return {
        "verdict": "SUBJECT_EXISTS" if real else "NO_SUBJECT",
        "reason": "" if real else "ни одного не-demo хода книги в журнале",
        "moves": len(real),
        "moves_demo_skipped": demo,
        "first_move": stamps[0].isoformat() if stamps else None,
        "last_move": stamps[-1].isoformat() if stamps else None,
        "gross_moved_usd": round(gross, 2),
        "senses": SUBJECT_SENSES,
        "verifies_sense": STAGE_VERIFIES_SENSE,
    }


def measure_stage(root: Path) -> dict[str, Any]:
    """Вопрос 2а: ступень и её продукт — по объявлению §46, без своей копии."""
    try:
        from spa_core.monitoring.cio_component_map import STAGES
    except Exception as exc:  # noqa: BLE001 — импорт карты не смеет валить замер
        return {"verdict": PROV_UNCHECKED,
                "reason": f"карта §46 не читается: {type(exc).__name__}: {exc}"}
    stage = next((s for s in STAGES if s.key == STAGE_KEY), None)
    if stage is None:
        return {"verdict": PROV_UNCHECKED,
                "reason": (f"в карте §46 нет ступени `{STAGE_KEY}` — состав "
                           "ступеней изменился, и замер обязан это СКАЗАТЬ, "
                           "а не завести свою копию таблицы")}

    art_rel = f"data/{stage.product}"
    doc, err = _read_json(root / art_rel)
    out: dict[str, Any] = {
        "verdict": "OK",
        "stage_key": stage.key,
        "owner_name": stage.owner_name,
        "module": stage.module,
        "artifact": art_rel,
        "entry": list(stage.entry),
    }
    if err is not None:
        out["verdict"] = PROV_UNCHECKED
        out["reason"] = f"{art_rel}: {err}"
        return out
    if not isinstance(doc, dict):
        out["verdict"] = PROV_UNCHECKED
        out["reason"] = f"{art_rel}: ожидался объект, получен {type(doc).__name__}"
        return out

    out["generated_at"] = doc.get("generated_at")
    out["n_trades"] = doc.get("n_trades")
    out["says_matches_target"] = doc.get("matches_target")
    out["says_go_live_ready"] = doc.get("go_live_ready")
    out["book_in_artifact"] = {
        k: v for k, v in (doc.get("resulting_positions") or {}).items()
        if isinstance(v, (int, float))
    }
    out["nav_before_usd"] = doc.get("nav_before_usd")
    return out


def _iter_py(root: Path):
    for base in ("spa_core", "scripts"):
        d = root / base
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.py")):
            yield p


def _dotted(module_rel: str) -> str:
    return module_rel[:-3].replace("/", ".") if module_rel.endswith(".py") \
        else module_rel.replace("/", ".")


def _abs_import_module(node: ast.ImportFrom, file_rel: str) -> str:
    """Абсолютное имя модуля для `from … import …`, включая относительный вид."""
    if not node.level:
        return node.module or ""
    pkg = _dotted(file_rel).split(".")[:-1]          # пакет самого файла
    if node.level > 1:
        pkg = pkg[: -(node.level - 1)] or []
    return ".".join([*pkg, node.module]) if node.module else ".".join(pkg)


def _bindings(tree: ast.Module, file_rel: str, rec: Reconciler
              ) -> tuple[set[str], set[str]]:
    """Имена файла, привязанные к нашей функции и к её модулю.

    Форм ввоза четыре, и каждая даёт своё имя вызова:
    ``from …reconciliation import reconcile`` (голое имя) ·
    ``from spa_core.execution import reconciliation as rc`` (``rc.reconcile``) ·
    ``import spa_core.execution.reconciliation as rc`` (то же) ·
    ``import spa_core.execution.reconciliation`` (полный путь).
    Учитывать только первую значило бы объявить «совпадением имени» настоящие
    вызовы — вторая половина той же ошибки, что и ложные срабатывания.
    """
    want_mod = _dotted(rec.module)
    pkg, _, leaf = want_mod.rpartition(".")
    func_names: set[str] = set()
    mod_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = _abs_import_module(node, file_rel)
            for a in node.names:
                if mod == want_mod and a.name == rec.func:
                    func_names.add(a.asname or a.name)
                elif mod == pkg and a.name == leaf:
                    mod_names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == want_mod:
                    mod_names.add(a.asname or a.name.split(".")[0])
    return func_names, mod_names


def _call_identity(call: ast.Call, file_rel: str, rec: Reconciler,
                   func_names: set[str], mod_names: set[str],
                   defines_own: bool) -> str:
    """Та ли это функция В ЭТОМ вызове — с учётом формы вызова."""
    f = call.func
    if isinstance(f, ast.Attribute):
        base = f.value
        if isinstance(base, ast.Name) and base.id in mod_names:
            return "imported"
        return "unrelated"
    if isinstance(f, ast.Name):
        if f.id in func_names:
            return "ambiguous" if defines_own else "imported"
        if file_rel == rec.module and not func_names:
            return "own"
        if defines_own:
            return "shadowed"
    return "unrelated"


def measure_inputs(root: Path) -> dict[str, Any]:
    """Вопрос 2б — ГЛАВНЫЙ: подаётся ли сверке НАБЛЮДЁННЫЙ исход.

    Себя из обхода исключаем намеренно (урок ADR-253 №4: сторож, читающий
    собственный корпус, находит себя и объявляет связь там, где её нет).
    """
    me = Path(__file__).name
    sites: list[dict[str, Any]] = []
    shadowed: list[dict[str, Any]] = []
    unparsed: list[dict[str, str]] = []

    for path in _iter_py(root):
        rel = path.relative_to(root).as_posix()
        if path.name == me:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError) as exc:
            unparsed.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue

        # Функция, внутри которой стои́т вызов — область присваиваний.
        owner: dict[ast.AST, ast.AST] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                for child in ast.walk(fn):
                    owner.setdefault(child, fn)

        binds = {}
        for rec in RECONCILERS:
            fn_names, mod_names = _bindings(tree, rel, rec)
            defines_own = any(
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == rec.func
                for n in ast.walk(tree))
            binds[rec.func] = (fn_names, mod_names, defines_own)

        cache: dict[int, dict[str, list[ast.AST]]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            for rec in RECONCILERS:
                if name != rec.func:
                    continue
                fn_names, mod_names, defines_own = binds[rec.func]
                who = _call_identity(node, rel, rec, fn_names, mod_names,
                                     defines_own)
                if who in ("shadowed", "unrelated"):
                    # Совпало ИМЯ, а не предмет. Отбрасывается молча только
                    # потому, что это не находка: чужая одноимённая функция
                    # ничего не говорит о нашей ступени. Счёт отброшенных
                    # печатается отдельно, чтобы «отбросили» не стало
                    # неотличимо от «не встретили».
                    shadowed.append({"file": rel, "line": node.lineno,
                                     "func": rec.func, "identity": who})
                    continue
                scope = owner.get(node, tree)
                key = id(scope)
                if key not in cache:
                    cache[key] = _assignments(scope)
                verdict = classify_resulting(node, rec, cache[key])
                if who == "ambiguous":
                    verdict = {"provenance": PROV_UNCHECKED,
                               "detail": (f"файл и ввозит `{rec.func}` из "
                                          f"{rec.module}, и определяет свою "
                                          "функцию с этим именем — какая из "
                                          "них вызвана, разбором не решить")}
                sites.append({
                    "file": rel,
                    "line": node.lineno,
                    "reconciler": f"{rec.module}::{rec.func}",
                    "identity": who,
                    "is_test": rel.startswith("spa_core/tests/")
                    or rel.startswith("tests/")
                    or "/tests/" in rel,
                    **verdict,
                })

    prod = [s for s in sites if not s["is_test"]]
    counts = {p: sum(1 for s in prod if s["provenance"] == p)
              for p in (PROV_SELF, PROV_LITERAL, PROV_OBSERVED, PROV_UNCHECKED)}
    return {
        "sites": sites,
        "sites_production": len(prod),
        "sites_test": len(sites) - len(prod),
        "counts": counts,
        "shadowed": shadowed,
        "shadowed_count": len(shadowed),
        "unparsed": unparsed,
        "reconcilers": [{"module": r.module, "func": r.func, "why": r.why}
                        for r in RECONCILERS],
    }


def measure_content(root: Path, stage: dict[str, Any]) -> dict[str, Any]:
    """Вопрос 3: книга артефакта против сегодняшней книги."""
    book, err = _read_json(root / BOOK_REL)
    if err is not None or not isinstance(book, dict):
        return {"verdict": PROV_UNCHECKED,
                "reason": f"{BOOK_REL}: {err or 'ожидался объект'}"}

    detail = book.get("positions_detail")
    live: dict[str, float] = {}
    if isinstance(detail, dict):
        for k, v in detail.items():
            if isinstance(v, dict) and isinstance(v.get("usd"), (int, float)):
                live[k] = float(v["usd"])
            elif isinstance(v, (int, float)):
                live[k] = float(v)
    elif isinstance(book.get("positions"), dict):
        for k, v in book["positions"].items():
            if isinstance(v, (int, float)):
                live[k] = float(v)
    if not live:
        return {"verdict": PROV_UNCHECKED,
                "reason": f"{BOOK_REL}: позиции не разобраны — судить не о чем"}

    art_book = stage.get("book_in_artifact") or {}
    if not art_book:
        return {"verdict": PROV_UNCHECKED,
                "reason": "в артефакте ступени нет книги — сверять нечего"}

    gone = sorted(set(art_book) - set(live))
    fresh = sorted(set(live) - set(art_book))
    shared = sorted(set(art_book) & set(live))
    same_amount = [k for k in shared if abs(art_book[k] - live[k]) < 1.0]

    art_ts = _parse_ts(stage.get("generated_at"))
    after = 0
    if art_ts is not None:
        trades, terr = _read_json(root / TRADES_REL)
        if terr is None and isinstance(trades, list):
            for t in trades:
                if not isinstance(t, dict) or t.get("is_demo"):
                    continue
                d = _parse_ts(t.get("ts"))
                if d is not None and d > art_ts:
                    after += 1

    return {
        "verdict": "OK" if not gone and len(same_amount) == len(shared) else "DIVERGED",
        "positions_in_artifact": len(art_book),
        "positions_live": len(live),
        "gone": gone,
        "new": fresh,
        "shared": shared,
        "shared_with_same_amount": same_amount,
        "moves_after_artifact": after,
        "artifact_nav_usd": stage.get("nav_before_usd"),
        "live_deployed_usd": book.get("deployed_usd"),
        "book_generated_at": book.get("generated_at"),
    }


def measure(root: Path) -> dict[str, Any]:
    subject = measure_subject(root)
    stage = measure_stage(root)
    inputs = measure_inputs(root)
    content = measure_content(root, stage)
    return {"subject": subject, "stage": stage, "inputs": inputs,
            "content": content}


# ────────────────────────── положительный контроль ───────────────────────────

def _control_tree(base: Path, *, resulting: str, trades: str,
                  artifact: bool = True) -> Path:
    """Собрать дерево-сцену. ``resulting`` — текст второго аргумента сверки."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "data").mkdir(exist_ok=True)
    (base / "spa_core/execution").mkdir(parents=True, exist_ok=True)
    (base / "spa_core/paper_trading").mkdir(parents=True, exist_ok=True)
    (base / "scripts").mkdir(exist_ok=True)

    (base / "spa_core/execution/reconciliation.py").write_text(
        "def reconcile(target, resulting, nav_before):\n"
        "    return {'matches_target': target == resulting}\n",
        encoding="utf-8")
    (base / "spa_core/paper_trading/pre_cutover_gate.py").write_text(
        "def nav_reconcile(target, resulting):\n"
        "    return {'matches_target': target == resulting}\n",
        encoding="utf-8")
    (base / "scripts/caller.py").write_text(
        "from spa_core.execution.reconciliation import reconcile\n"
        "\n"
        "def load(path):\n"
        "    return {}\n"
        "\n"
        "def go(allocation, path):\n"
        "    target = dict(allocation)\n"
        f"    resulting = {resulting}\n"
        "    return reconcile(target, resulting, 100.0)\n",
        encoding="utf-8")

    (base / "data/trades.json").write_text(trades, encoding="utf-8")
    (base / "data/current_positions.json").write_text(
        json.dumps({"generated_at": "2026-09-01T00:00:00+00:00",
                    "deployed_usd": 100.0,
                    "positions_detail": {"aave_v3": {"usd": 100.0}}}),
        encoding="utf-8")
    if artifact:
        (base / "data/execution_reconciliation.json").write_text(
            json.dumps({"generated_at": "2026-01-01T00:00:00+00:00",
                        "n_trades": 0, "matches_target": True,
                        "go_live_ready": True, "nav_before_usd": 50.0,
                        "resulting_positions": {"euler_v2": 50.0}}),
            encoding="utf-8")
    return base


_TRADES_ONE = json.dumps([{"trade_id": "T1", "ts": "2026-06-01T00:00:00+00:00",
                           "is_demo": False, "diff_usd": 500.0}])
_TRADES_NONE = json.dumps([])


def positive_control() -> dict[str, Any]:
    """Прибор ОБЯЗАН отличить сравнение с самим собой от сверки с наблюдением.

    Половин четыре, и каждая управляет своим ответом. Только «находящих»
    половин здесь нет намеренно: проверка, которая лишь находит, проходит и у
    сторожа, который находит ВСЕГДА (украшение, пойманное на своём авторе в
    #515 и #516). Поэтому две половины ОБРАТНЫЕ: наблюдение не должно
    объявляться сравнением с собой, а пустой трек не должен давать находку о
    протухшем артефакте.
    """
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        def prov(tree: Path) -> str:
            got = measure_inputs(tree)
            prod = [s for s in got["sites"] if not s["is_test"]]
            return prod[0]["provenance"] if prod else "НЕТ ВЫЗОВА"

        t = _control_tree(base / "self", resulting="dict(target)",
                          trades=_TRADES_ONE)
        got = prov(t)
        checks.append({"name": "сравнение величины с самой собой видно",
                       "expected": PROV_SELF, "got": got,
                       "passed": got == PROV_SELF})

        t = _control_tree(base / "chain", resulting="apply(dict(target))",
                          trades=_TRADES_ONE)
        got = prov(t)
        checks.append({"name": "происхождение через цепочку присваиваний видно",
                       "expected": PROV_SELF, "got": got,
                       "passed": got == PROV_SELF})

        t = _control_tree(base / "observed", resulting="load(path)",
                          trades=_TRADES_ONE)
        got = prov(t)
        checks.append({"name": "СВЕРКА С НАБЛЮДЕНИЕМ находкой НЕ является",
                       "expected": PROV_OBSERVED, "got": got,
                       "passed": got == PROV_OBSERVED})

        t = _control_tree(base / "nosubject", resulting="dict(target)",
                          trades=_TRADES_NONE)
        subj = measure_subject(t)
        stage = measure_stage(t)
        fnd = _findings({"subject": subj, "stage": stage,
                         "inputs": measure_inputs(t),
                         "content": measure_content(t, stage)})
        stale = [f for f in fnd if f.get("code") == "STALE_VS_EXECUTIONS"]
        checks.append({"name": "пустой трек НЕ даёт находки о протухшем артефакте",
                       "expected": "находки нет",
                       "got": "находки нет" if not stale else "находка есть",
                       "passed": not stale and subj["verdict"] == "NO_SUBJECT"})

        t = _control_tree(base / "noartifact", resulting="dict(target)",
                          trades=_TRADES_ONE, artifact=False)
        st = measure_stage(t)
        checks.append({"name": "артефакта нет ⇒ UNCHECKED, а не чистый проход",
                       "expected": PROV_UNCHECKED, "got": st["verdict"],
                       "passed": st["verdict"] == PROV_UNCHECKED})

    return {"passed": all(c["passed"] for c in checks), "checks": checks}


# ─────────────────────────────── находки ─────────────────────────────────────

def _findings(meas: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    subject = meas["subject"]
    stage = meas["stage"]
    inputs = meas["inputs"]
    content = meas["content"]

    if subject["verdict"] == PROV_UNCHECKED:
        out.append({"severity": "unchecked", "code": "SUBJECT_UNCHECKED",
                    "text": f"есть ли предмет верификации — НЕ ИЗМЕРЕНО: "
                            f"{subject['reason']}"})
    elif subject["verdict"] == "NO_SUBJECT":
        out.append({"severity": "info", "code": "NO_SUBJECT",
                    "text": ("предмета верификации сегодня НЕТ: ни одного хода "
                             "книги. Это полный ответ, а не отказ — верифицировать "
                             "нечего, и возраст продукта ступени находкой не является")})

    if stage["verdict"] == PROV_UNCHECKED:
        out.append({"severity": "unchecked", "code": "STAGE_UNCHECKED",
                    "text": f"ступень §46 `{STAGE_KEY}` не измерена: {stage.get('reason')}"})

    # ГЛАВНАЯ находка: сверке никогда не подают наблюдённый исход.
    c = inputs["counts"]
    if inputs["sites_production"] and not c[PROV_OBSERVED]:
        out.append({
            "severity": "critical", "code": "NEVER_ASKED_ABOUT_REALITY",
            "text": (
                f"сверка «намерение против результата» вызывается "
                f"{inputs['sites_production']} раз(а) вне тестов, и НИ ОДИН вызов "
                f"не подаёт ей наблюдённый исход: "
                f"{c[PROV_SELF]} получают второй аргумент ИЗ ПЕРВОГО того же "
                f"вызова, {c[PROV_LITERAL]} — литералом, "
                f"{c[PROV_UNCHECKED]} не разобрано. То есть проверяется "
                "равенство величины самой себе, и расхождение недостижимо ПО "
                "ПОСТРОЕНИЮ. Сверка при этом рабочая — испорченную копию она "
                "ловит; находка в том, что её вопрос никогда не задают о книге")})
    elif inputs["sites_production"] and c[PROV_OBSERVED]:
        out.append({"severity": "info", "code": "OBSERVED_INPUT_EXISTS",
                    "text": (f"вызовов сверки с наблюдённым исходом: "
                             f"{c[PROV_OBSERVED]} из {inputs['sites_production']}")})
    elif not inputs["sites_production"]:
        out.append({"severity": "unchecked", "code": "NO_CALL_SITES",
                    "text": ("вызовов сверки вне тестов не найдено вовсе — "
                             "либо объявление `RECONCILERS` устарело, либо "
                             "ступень не зовут; и то и другое надо разобрать, "
                             "а не считать чистым проходом")})

    if c[PROV_UNCHECKED]:
        out.append({"severity": "unchecked", "code": "PROVENANCE_UNCHECKED",
                    "text": (f"происхождение исхода не разобрано у "
                             f"{c[PROV_UNCHECKED]} вызов(а/ов) — «не измерено», "
                             "а не «подаётся наблюдение»")})

    if inputs["unparsed"]:
        out.append({"severity": "unchecked", "code": "FILES_UNPARSED",
                    "text": (f"не разобрано файлов: {len(inputs['unparsed'])} "
                             f"(первый: {inputs['unparsed'][0]['file']})")})

    # Протухание — ТОЛЬКО при наличии предмета, и гейт здесь ОДИН, а не два.
    #
    # Здесь стоял ещё и конъюнкт `subject["verdict"] == "SUBJECT_EXISTS"`.
    # Харнесс мутаций показал, что он ИЗБЫТОЧЕН ПО ПОСТРОЕНИЮ: `moves_after_
    # artifact` считает не-demo ходы строго позже отметки артефакта, и если их
    # хоть один, предмет существует по определению — ложным этот конъюнкт стать
    # не может. Убран не «чтобы мутация покраснела», а потому что условие,
    # которое невозможно нарушить, СОЗДАЁТ ложное впечатление проверки:
    # тест на него проходит и со сторожем, и без него (класс «украшение»,
    # #515/#516). Свойство «нет предмета ⇒ нет находки» держит сам счётчик.
    if content.get("moves_after_artifact"):
        out.append({
            "severity": "critical", "code": "STALE_VS_EXECUTIONS",
            "text": (
                f"продукт ступени написан {stage.get('generated_at')}, а после "
                f"этого книга ходила {content['moves_after_artifact']} раз "
                f"(всего за трек {subject['moves']}, перело́жено "
                f"${subject['gross_moved_usd']:,.2f}). Ни один из этих ходов "
                f"ступенью не верифицирован, а её последнее слово — "
                f"`n_trades={stage.get('n_trades')}`, "
                f"`matches_target={stage.get('says_matches_target')}`, "
                f"`go_live_ready={stage.get('says_go_live_ready')}`")})

    if content.get("verdict") == "DIVERGED":
        out.append({
            "severity": "warn", "code": "BOOK_NO_LONGER_EXISTS",
            "text": (
                f"книга в продукте ступени — не сегодняшняя: из "
                f"{content['positions_in_artifact']} позиций исчезли "
                f"{len(content['gone'])} ({', '.join(content['gone']) or '—'}), "
                f"появились {len(content['new'])} "
                f"({', '.join(content['new']) or '—'}); из "
                f"{len(content['shared'])} общих ключ(а/ей) сумма сошлась у "
                f"{len(content['shared_with_same_amount'])}. NAV артефакта "
                f"${content.get('artifact_nav_usd')} против развёрнутых "
                f"${content.get('live_deployed_usd')}")})
    elif content.get("verdict") == PROV_UNCHECKED:
        out.append({"severity": "unchecked", "code": "CONTENT_UNCHECKED",
                    "text": f"содержимое не сверено: {content.get('reason')}"})

    return out


def run(root: str | Path | None = None, *, write: bool = True,
        now: datetime | None = None) -> dict[str, Any]:
    """Собрать отчёт §5 (последняя ступень). ``now`` — ВХОД, не окружение."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    ts = (now or datetime.now(timezone.utc)).isoformat()

    control = positive_control()
    meas = measure(root)
    findings = _findings(meas)

    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "critical"),
        "warn": sum(1 for f in findings if f["severity"] == "warn"),
        "info": sum(1 for f in findings if f["severity"] == "info"),
        "unchecked": sum(1 for f in findings if f["severity"] == "unchecked"),
    }
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
        "schema": "cio_post_trade_verification/v1",
        "generated_at": ts,
        "overall": overall,
        "counts": counts,
        "positive_control": control,
        "subject": meas["subject"],
        "stage": meas["stage"],
        "inputs": meas["inputs"],
        "content": meas["content"],
        "findings": findings,
        "advisory": ("ADVISORY: ступени НЕ подаётся фактический исход и ни один "
                     "вызов не изменён. Подать сверке наблюдённую книгу значит "
                     "изменить путь принятия решения о капитале — money-path и "
                     "решение владельца."),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(root) / REPORT_REL))
    return doc


def main() -> int:
    doc = run(root=os.environ.get("SPA_ROOT") or None)
    s, i = doc["subject"], doc["inputs"]
    print(f"cio_post_trade_verification: {doc['overall']} "
          f"(critical={doc['counts']['critical']} warn={doc['counts']['warn']} "
          f"unchecked={doc['counts']['unchecked']}) · предмет: {s['verdict']} "
          f"({s.get('moves')} ход(а/ов) книги) · вызовов сверки вне тестов "
          f"{i['sites_production']}, из них с наблюдённым исходом "
          f"{i['counts'][PROV_OBSERVED]}")
    for f in doc["findings"]:
        print(f"  [{f['severity'].upper()}] {f['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
