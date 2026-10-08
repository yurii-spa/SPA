"""Порог сенсора против ТАКТА предмета: сторож, чей порог свежести объявлен
МЕНЬШЕ такта того, что он мерит, красен по построению.

Заказ владельца **G146 п. 2** (хвост `ADR-645`, цикл #801) дословно:

> «**`STALE_PUSH_HOURS` / `STALE_CYCLE_HOURS` — класс „порог сенсора против
> такта предмета“**, а не два случая: у скольких сторожей порог свежести
> объявлен МЕНЬШЕ такта того, что он мерит. Такой сторож красен по построению
> и учит себя не читать.»

Вред, ради которого прибор написан
---------------------------------------------------------------------------
Сторож свежести отвечает на вопрос «давно ли это писали». Ответ сравнивается с
порогом, и порог обязан быть БОЛЬШЕ такта писателя — иначе красный наступает не
от поломки, а от календаря. Дневной артефакт под порогом 2 ч красен **22 ч из
24 по построению**: вердикт такого сторожа не несёт сведений ни в одном из двух
своих состояний, и читатель быстро выучивает, что эту строку надо пропускать.

Это ВТОРОЙ род вреда рядом с тем, который разбирал ряд ADR-526…645. Там
спрашивалось «читает ли находку хоть кто-нибудь»; здесь находка прочитана, но
её нечем отличить от тика часов. Молчащий сторож и сторож, красный всегда,
гасятся читателем ОДИНАКОВО, и второй при этом выглядит работающим.

Что именно меряется: ДВЕ ФОРМЫ одного класса
---------------------------------------------------------------------------
**Форма «объявленная» (`declared`).** Конституция (``architecture/manifest.json``)
несёт у каждой пары «производитель → артефакт» порог ``slo_hours``, а у
производителя — ``schedule``. Оба числа — ОБЪЯВЛЕНИЯ, поэтому вердикт этой формы
сомнения не оставляет: ``slo_hours`` меньше такта производителя значит, что
сторож свежести артефакта обязан краснеть между двумя исправными прогонами.

**Форма «в коде» (`in_code`).** Порог живёт константой модуля
(``STALE_CYCLE_HOURS = 2.0``), а предмет — путём артефакта, прочитанным в той же
функции. Вердикт этой формы НЕ есть «сторож красен»: писатель артефакта может
быть НЕ ОБЪЯВЛЕН, и тогда реальный такт короче расписания. Поэтому находка здесь
называется **ПРОТИВОРЕЧИЕМ ОБЪЯВЛЕНИЙ**: один из двух номеров неверен, и какой
именно — решается замером писателя, а не чтением деклараций. Разница существенна,
и смешать их значило бы выдать незнание за находку.

**Третья ось — `contradiction`.** Когда у одного артефакта есть И порог
конституции, И порог в коде, они сравниваются между собой: ``slo_hours = 26``
против ``STALE_CYCLE_HOURS = 2.0`` у ``data/paper_trading_status.json`` — два
числа об одном предмете, расходящиеся в тринадцать раз. Эта ось не выводится из
двух первых: оба порога могут иметь запас к такту и всё равно противоречить друг
другу.

Такт считается по ВСЕМ производителям, а не по одному
---------------------------------------------------------------------------
Первая редакция считала такт у производителя и объявила находкой
``data/deployment_acceptance.json`` (``slo_hours = 15`` против суточного
``calendar:20:00``). Находка была ЛОЖНОЙ: тот же артефакт пишет второй агент в
``08:00``, и худший разрыв равен 12 ч, а не 24. Поэтому такт — свойство
АРТЕФАКТА: расписания всех его производителей раскладываются в минуты НЕДЕЛИ, и
берётся наибольший разрыв по кругу. Интервальный производитель даёт свою границу
сам, и общий такт есть МИНИМУМ доступных границ: каждый писатель гарантирует
разрыв не больше своего такта, и достаточно одного.

Третий исход назван ОТДЕЛЬНО и в НЁМ четыре причины
---------------------------------------------------------------------------
«Не измерено» никогда не выдаётся за «с запасом» (инв. #17):

* ``tact_unknown`` — у производителя такта нет ВОВСЕ (``daemon``, ``manual``,
  ``event:watchpaths``, расписание не объявлено) или форма расписания не
  разобрана. Порог против отсутствующего такта сравнить нечем;
* ``unit_undeclared`` — имя константы не называет единицу
  (``APY_FEED_STALE_CYCLES_ALERT`` мерит ЦИКЛЫ, а не время). Единица
  спрашивается у ИМЕНИ и только у него: догадка по значению — ровно та подмена,
  из-за которой ``ADR-645`` получил возраст «НЕ ИЗМЕРЕН» на отчёте
  четырёхминутной давности;
* ``subject_unresolved`` — дорога от сравниваемого значения до пути артефакта не
  прошла. Так отвечает ``STALE_PUSH_HOURS``: его предмет — вывод ``git log``, а
  не артефакт конституции, и такта у «пуша» не объявлено нигде;
* ``subject_ambiguous`` — дорога привела к ДВУМ и более артефактам. Выбрать
  один значило бы угадать предмет сторожа.

Чего прибор НЕ докладывает (названо, а не умолчано)
---------------------------------------------------------------------------
* **Наблюдённый такт.** Все такты здесь ОБЪЯВЛЕННЫЕ. Артефакт, который пишут
  чаще расписания (``data/paper_trading_status.json`` обновлялся за 3 мин до
  замера при суточном ``calendar:08:00``), держится на НЕЗАЯВЛЕННОМ писателе, и
  сторож с коротким порогом на нём зелен. Это и делает форму «в коде»
  противоречием деклараций, а не приговором сторожу;
* **исполняется ли сравнение.** Дорога по дереву есть достижимость, а не
  исполнение;
* **верен ли сам порог.** Прибор сравнивает порог с тактом и не знает, каким
  порог ДОЛЖЕН быть: правильное число берётся из распределения разрывов
  писателя, а это замер, а не чтение (так и получен ``slo_hours = 2`` у
  ``data/code_sync_status.json``);
* ``applied=False`` — прибор только ЧИТАЕТ. Ни один порог он не правит: порог
  есть контракт сторожа, и менять его молча запрещено (инв. #16).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable

#: Прибор ничего не правит: он ЧИТАЕТ дерево и конституцию.
APPLIED = False

#: Единый ярлык третьего исхода — его же печатает шаг 0-офис.
NOT_MEASURED = "НЕ ИЗМЕРЕНО"

#: Конституция флота: расписания производителей и пороги `slo_hours`.
CONSTITUTION = Path("architecture") / "manifest.json"

#: Каталоги рантайма, в которых ищутся пороги в коде. Тесты сюда не входят
#: намеренно: порог теста есть часть сцены, а не контракт сторожа.
CODE_ROOTS = ("spa_core", "scripts")

#: Лексикон имён, за которыми стоит порог свежести. Имя — ОБЪЯВЛЕНИЕ автора;
#: угадывать порог по значению прибор не вправе.
FRESHNESS_LEXICON = re.compile(
    r"(STALE|FRESH|MAX_AGE|AGE_MAX|OVERDUE|SLO|TTL|EXPIR)", re.IGNORECASE)

#: Единица времени объявляется СУФФИКСОМ имени. Порядок важен: длинный суффикс
#: проверяется раньше короткого, иначе `_MINUTES` прочитается как `_S`.
UNIT_SUFFIXES: tuple[tuple[str, float], ...] = (
    ("_SECONDS", 1.0 / 3600.0),
    ("_SECS", 1.0 / 3600.0),
    ("_SEC", 1.0 / 3600.0),
    ("_MINUTES", 1.0 / 60.0),
    ("_MINS", 1.0 / 60.0),
    ("_MIN", 1.0 / 60.0),
    ("_HOURS", 1.0),
    ("_HRS", 1.0),
    ("_DAYS", 24.0),
    ("_WEEKS", 168.0),
    ("_H", 1.0),
    ("_S", 1.0 / 3600.0),
)

#: Сравнения, которыми судят возраст. Равенство в этот набор не входит:
#: `age == THRESHOLD` вердикта о свежести не выносит.
ORDER_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)

MINUTES_IN_WEEK = 7 * 24 * 60


# ---------------------------------------------------------------------------
# Такт: расписание → минуты недели
# ---------------------------------------------------------------------------

def schedule_bound(schedule: Any) -> tuple[float | None, set[int] | None, str | None]:
    """Разобрать расписание производителя.

    Возвращает ``(граница_в_часах, минуты_недели, причина_третьего_исхода)``.
    Ровно одно из первых двух значений не ``None`` при пустой причине: у
    интервального расписания граница известна сразу, у календарного она
    выводится из объединённых минут недели (одно расписание ещё не знает о
    соседних производителях того же артефакта).
    """
    if schedule is None or schedule == "":
        return None, None, "расписание не объявлено"
    text = str(schedule)

    interval = re.fullmatch(r"interval:(\d+(?:\.\d+)?)s", text)
    if interval:
        return float(interval.group(1)) / 3600.0, None, None

    if text == "daemon":
        return None, None, "daemon — такта нет по построению"
    if text == "manual":
        return None, None, "manual — запускает человек, такта нет"
    if text.startswith("event:"):
        return None, None, f"событийный запуск ({text}) — такта нет"

    if text.startswith("calendar:minute:"):
        minute = re.fullmatch(r"calendar:minute:(\d+)", text)
        if not minute:
            return None, None, f"форма расписания не разобрана: {text}"
        at = int(minute.group(1)) % 60
        return None, {d * 1440 + h * 60 + at
                      for d in range(7) for h in range(24)}, None

    if text.startswith("calendar:"):
        minutes: set[int] = set()
        for slot in text[len("calendar:"):].split(","):
            slot = slot.strip()
            weekly = re.fullmatch(r"wd(\d)·(\d{1,2}):(\d{2})", slot)
            if weekly:
                # launchd Weekday: 0 и 7 — воскресенье; к понедельнику-нулю
                # приводим так же, как это делает сам launchd.
                wd = int(weekly.group(1)) % 7
                day = (wd - 1) % 7
                minutes.add(day * 1440 + int(weekly.group(2)) * 60
                            + int(weekly.group(3)))
                continue
            daily = re.fullmatch(r"(\d{1,2}):(\d{2})", slot)
            if daily:
                at = int(daily.group(1)) * 60 + int(daily.group(2))
                minutes.update(d * 1440 + at for d in range(7))
                continue
            return None, None, f"форма расписания не разобрана: {text}"
        if not minutes:
            return None, None, f"форма расписания не разобрана: {text}"
        return None, minutes, None

    return None, None, f"форма расписания не разобрана: {text}"


def _max_gap_hours(minutes: set[int]) -> float:
    """Наибольший разрыв между прогонами по КРУГУ недели, в часах."""
    ordered = sorted(minutes)
    if len(ordered) == 1:
        return MINUTES_IN_WEEK / 60.0
    gaps = [(ordered[(i + 1) % len(ordered)] - ordered[i]) % MINUTES_IN_WEEK
            for i in range(len(ordered))]
    return max(gaps) / 60.0


def combined_tact(schedules: Iterable[Any]) -> tuple[float | None, list[str]]:
    """Такт АРТЕФАКТА по всем его производителям.

    Каждый писатель сам гарантирует разрыв не больше своего такта, поэтому
    общая граница есть МИНИМУМ доступных границ. Календарные писатели
    складываются точнее: их минуты объединяются в один круг недели.
    """
    bounds: list[float] = []
    reasons: list[str] = []
    calendar_minutes: set[int] = set()
    for schedule in schedules:
        hours, minutes, why = schedule_bound(schedule)
        if why:
            reasons.append(why)
            continue
        if hours is not None:
            bounds.append(hours)
        if minutes:
            calendar_minutes |= minutes
    if calendar_minutes:
        bounds.append(_max_gap_hours(calendar_minutes))
    if not bounds:
        return None, reasons
    return min(bounds), reasons


# ---------------------------------------------------------------------------
# Конституция: артефакт → такт, артефакт → объявленный порог
# ---------------------------------------------------------------------------

def load_constitution(root: Path) -> dict[str, Any]:
    path = root / CONSTITUTION
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_tacts(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Собрать по каждому артефакту: такт, производителей, объявленные пороги."""
    table: dict[str, dict[str, Any]] = {}

    def slot(path: str) -> dict[str, Any]:
        return table.setdefault(path, {
            "producers": [],
            "schedules": [],
            "declared_slo": {},   # производитель → slo_hours (у `produces`)
            "artifact_slo": None,  # slo_hours из перечня `artifacts`
        })

    by_label = {a.get("label"): a for a in manifest.get("agents") or []}
    for agent in manifest.get("agents") or []:
        for produced in agent.get("produces") or []:
            path = produced.get("artifact")
            if not path:
                continue
            entry = slot(path)
            entry["producers"].append(agent.get("label"))
            entry["schedules"].append(agent.get("schedule"))
            entry["declared_slo"][agent.get("label")] = produced.get("slo_hours")

    for artifact in manifest.get("artifacts") or []:
        path = artifact.get("path")
        if not path:
            continue
        entry = slot(path)
        entry["artifact_slo"] = artifact.get("slo_hours")
        producer = artifact.get("producer")
        if producer and producer not in entry["producers"]:
            entry["producers"].append(producer)
            entry["schedules"].append((by_label.get(producer) or {}).get("schedule"))

    for path, entry in table.items():
        tact, reasons = combined_tact(entry["schedules"])
        entry["tact_hours"] = tact
        entry["tact_reasons"] = reasons
    return table


# ---------------------------------------------------------------------------
# Форма «объявленная»: slo_hours против такта производителей
# ---------------------------------------------------------------------------

def measure_declared(table: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Каждый объявленный порог свежести — против такта своего артефакта."""
    rows: list[dict[str, Any]] = []
    for path in sorted(table):
        entry = table[path]
        tact = entry["tact_hours"]
        declared: list[tuple[str, Any]] = [
            (f"produces[{label}]", value)
            for label, value in sorted(entry["declared_slo"].items())
        ]
        if entry["artifact_slo"] is not None:
            declared.append(("artifacts[]", entry["artifact_slo"]))
        for where, slo in declared:
            row = {
                "artifact": path,
                "where": where,
                "threshold_hours": slo,
                "tact_hours": tact,
                "producers": list(entry["producers"]),
                "schedules": list(entry["schedules"]),
            }
            if slo is None:
                row["verdict"] = "unit_undeclared"
                row["reason"] = "slo_hours не объявлен"
            elif tact is None:
                row["verdict"] = "tact_unknown"
                row["reason"] = "; ".join(entry["tact_reasons"]) or "такт не выведен"
            elif slo < tact:
                row["verdict"] = "below_tact"
                row["reason"] = (f"порог {slo} ч меньше такта {tact:.2f} ч — "
                                 f"красен {tact - slo:.2f} ч каждого такта")
            elif slo == tact:
                row["verdict"] = "no_margin"
                row["reason"] = (f"порог равен такту ({tact:.2f} ч) — запаса на "
                                 f"дрожание нет, красный от задержки прогона")
            else:
                row["verdict"] = "has_margin"
                row["reason"] = None
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Форма «в коде»: константа-порог против такта артефакта, который она судит
# ---------------------------------------------------------------------------

def declared_unit_hours(name: str) -> float | None:
    """Множитель к часам, объявленный СУФФИКСОМ имени, либо ``None``.

    Единица спрашивается у имени и только у него. Значение единицы не несёт:
    ``2.0`` одинаково правдоподобно как часы и как секунды, и догадка по
    величине есть ровно та подстановка, которую запрещает инв. #17.
    """
    upper = name.upper()
    for suffix, factor in UNIT_SUFFIXES:
        if upper.endswith(suffix):
            return factor
    return None


def _module_thresholds(tree: ast.Module) -> dict[str, float]:
    """Числовые константы уровня модуля, чьё имя обещает порог свежести."""
    found: dict[str, float] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant):
            continue
        if isinstance(value.value, bool) or not isinstance(value.value, (int, float)):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and FRESHNESS_LEXICON.search(target.id):
                found[target.id] = float(value.value)
    return found


def _assignments(scope: ast.AST) -> dict[str, list[ast.AST]]:
    """Имя → выражения, которые ему присваивали в этой области."""
    table: dict[str, list[ast.AST]] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value: ast.AST = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            targets = [node.optional_vars]
            value = node.context_expr
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                table.setdefault(target.id, []).append(value)
    return table


#: Имена, по которым видно, что значение пришло С ДИСКА.
DISK_READERS = frozenset({
    "open", "read_text", "read_bytes", "load", "loads", "stat", "getmtime",
    "st_mtime", "getctime", "glob", "rglob", "iterdir", "exists", "is_file",
})

#: Имена, по которым видно, что значение пришло от ВНЕШНЕЙ КОМАНДЫ.
COMMAND_RUNNERS = frozenset({"run", "check_output", "Popen", "getoutput", "system"})

#: Литерал, похожий на путь: расширение артефакта либо косая черта.
PATHLIKE = re.compile(r"(\.(json|jsonl|md|txt|csv|db|log|ya?ml|html|tsv)$|/)")


def _origin_facts(node: ast.AST,
                  local: dict[str, list[ast.AST]],
                  module_level: dict[str, list[ast.AST]]
                  ) -> tuple[set[str], set[str]]:
    """Строковые литералы и ПРИЗНАКИ источника, из которых значение происходит.

    Дорога считается до неподвижной точки по присваиваниям области. Два правила
    в ней не вкусовые, и оба найдены замером, а не придуманы:

    **Область разрешается как в Python, а не объединением.** Имя, которому
    присваивают в функции, ЛОКАЛЬНО, и модульное присваивание того же имени к
    делу не относится. Первая редакция складывала оба словаря и получила на
    ``uptime_monitor.STALE_CYCLE_HOURS`` исход ``subject_ambiguous``: к честному
    предмету (``paper_trading_status.json``) примешался модульный литерал
    ``uptime_prev_state.json`` через совпавшее имя. Предмет назван
    НЕРАЗОБРАННЫМ там, где он разобран, — то есть именно та находка, ради
    которой прибор написан, пропала бы в третьем исходе.

    **Контейнер привязкой НЕ является** (урок аварии 2026-08-04,
    `.claude/rules/deployment.md`): в словарь-результат
    (``{"ok": ..., "file": "x.json"}``) прибор не спускается, иначе «RHS
    поминает литерал» оправдало бы любую случайную близость.
    """
    seen: set[str] = set()
    literals: set[str] = set()
    flags: set[str] = set()
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Dict):
            continue
        if isinstance(current, ast.Constant) and isinstance(current.value, str):
            literals.add(current.value)
            continue
        if isinstance(current, ast.Name):
            if current.id in seen:
                continue
            seen.add(current.id)
            source = local.get(current.id)
            if source is None:
                source = module_level.get(current.id, [])
            stack.extend(source)
            continue
        if isinstance(current, ast.Call):
            called = current.func
            name = (called.attr if isinstance(called, ast.Attribute)
                    else called.id if isinstance(called, ast.Name) else None)
            if name in DISK_READERS:
                flags.add("disk")
            if name in COMMAND_RUNNERS:
                flags.add("command")
        if isinstance(current, ast.Attribute) and current.attr in DISK_READERS:
            flags.add("disk")
        for child in ast.iter_child_nodes(current):
            stack.append(child)
    return literals, flags


def _module_level_assignments(tree: ast.Module,
                              functions: list[ast.AST]) -> dict[str, list[ast.AST]]:
    """Присваивания, сделанные ВНЕ функций модуля."""
    nested = frozenset(id(inner) for func in functions for inner in ast.walk(func))
    table: dict[str, list[ast.AST]] = {}
    for name, values in _assignments(tree).items():
        outer = [value for value in values if id(value) not in nested]
        if outer:
            table[name] = outer
    return table


def _subject_index(table: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Литерал (полный путь и базовое имя) → артефакты конституции."""
    index: dict[str, list[str]] = {}
    for path in table:
        index.setdefault(path, []).append(path)
        index.setdefault(Path(path).name, []).append(path)
    return index


def _threshold_comparisons(scope: ast.AST,
                           thresholds: dict[str, float],
                           skip: frozenset[int] = frozenset()
                           ) -> list[tuple[str, ast.AST]]:
    """Сравнения ПОРЯДКА, в которых участвует порог. Возвращает (имя, другой операнд).

    ``skip`` несёт узлы, принадлежащие вложенным функциям: при обходе модуля они
    пропускаются, потому что их имена разрешаются в СВОЕЙ области. Без этого одно
    и то же сравнение судилось бы дважды и во второй раз — чужими присваиваниями.
    """
    pairs: list[tuple[str, ast.AST]] = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Compare) or id(node) in skip:
            continue
        operands = [node.left, *node.comparators]
        if not any(isinstance(op, ORDER_OPS) for op in node.ops):
            continue
        for index, operand in enumerate(operands):
            if not (isinstance(operand, ast.Name) and operand.id in thresholds):
                continue
            for other_index, other in enumerate(operands):
                if other_index != index:
                    pairs.append((operand.id, other))
    return pairs


def measure_in_code(root: Path,
                    table: dict[str, dict[str, Any]],
                    code_roots: Iterable[str] = CODE_ROOTS) -> list[dict[str, Any]]:
    """Пороги свежести в коде — против такта артефакта, который они судят."""
    index = _subject_index(table)
    rows: list[dict[str, Any]] = []
    for code_root in code_roots:
        base = root / code_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if "/tests/" in relative or path.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError) as exc:
                rows.append({
                    "module": relative, "constant": None, "verdict": "file_unparsed",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "artifact": None, "threshold_hours": None, "tact_hours": None,
                })
                continue
            thresholds = _module_thresholds(tree)
            if not thresholds:
                continue
            functions = [node for node in ast.walk(tree)
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            nested = frozenset(id(inner)
                               for func in functions
                               for inner in ast.walk(func))
            module_assigns = _module_level_assignments(tree, functions)
            seen_pairs: set[tuple[str, str]] = set()
            for scope in [tree, *functions]:
                if scope is tree:
                    local: dict[str, list[ast.AST]] = {}
                    pairs = _threshold_comparisons(scope, thresholds, nested)
                else:
                    local = _assignments(scope)
                    pairs = _threshold_comparisons(scope, thresholds)
                for constant, other in pairs:
                    literals, flags = _origin_facts(other, local, module_assigns)
                    subjects = sorted({artifact
                                       for literal in literals
                                       for artifact in index.get(literal, [])})
                    pathlike = sorted(literal for literal in literals
                                      if PATHLIKE.search(literal))
                    key = (constant, "|".join(subjects))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    row: dict[str, Any] = {
                        "module": relative,
                        "constant": constant,
                        "raw_value": thresholds[constant],
                        "artifact": subjects[0] if len(subjects) == 1 else None,
                        "subjects": subjects,
                        "threshold_hours": None,
                        "tact_hours": None,
                    }
                    unit = declared_unit_hours(constant)
                    if not subjects:
                        if pathlike or "disk" in flags:
                            row["verdict"] = "subject_not_declared"
                            row["reason"] = (
                                "предмет читается с диска, но в конституции не "
                                "объявлен — такта у него нет нигде"
                                + (f" (путь: {', '.join(pathlike[:3])})"
                                   if pathlike else ""))
                        elif "command" in flags:
                            row["verdict"] = "subject_not_declared"
                            row["reason"] = ("предмет — вывод внешней команды "
                                             "(`subprocess`), такта у него не "
                                             "объявлено нигде")
                        else:
                            row["verdict"] = "outside_population"
                            row["reason"] = ("сравниваемое значение не происходит ни "
                                             "от чтения с диска, ни от внешней "
                                             "команды — это не сторож свежести "
                                             "производимого (таймаут сети, срок "
                                             "кэша в памяти)")
                        rows.append(row)
                        continue
                    if len(subjects) > 1:
                        row["verdict"] = "subject_ambiguous"
                        row["reason"] = ("дорога привела к нескольким артефактам: "
                                         + ", ".join(subjects))
                        rows.append(row)
                        continue
                    if unit is None:
                        row["verdict"] = "unit_undeclared"
                        row["reason"] = (f"имя {constant} не называет единицу времени "
                                         f"— сравнить с тактом нечем")
                        rows.append(row)
                        continue
                    entry = table[subjects[0]]
                    hours = thresholds[constant] * unit
                    row["threshold_hours"] = hours
                    row["tact_hours"] = entry["tact_hours"]
                    row["producers"] = list(entry["producers"])
                    row["schedules"] = list(entry["schedules"])
                    if entry["tact_hours"] is None:
                        row["verdict"] = "tact_unknown"
                        row["reason"] = ("; ".join(entry["tact_reasons"])
                                         or "такт не выведен")
                    elif hours < entry["tact_hours"]:
                        row["verdict"] = "below_tact"
                        row["reason"] = (
                            f"порог {hours:.3g} ч меньше ОБЪЯВЛЕННОГО такта "
                            f"{entry['tact_hours']:.2f} ч — одно из двух объявлений "
                            f"неверно")
                    elif hours == entry["tact_hours"]:
                        row["verdict"] = "no_margin"
                        row["reason"] = (f"порог равен объявленному такту "
                                         f"{entry['tact_hours']:.2f} ч — запаса нет")
                    else:
                        row["verdict"] = "has_margin"
                        row["reason"] = None
                    rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Третья ось: два порога об ОДНОМ артефакте, расходящиеся между собой
# ---------------------------------------------------------------------------

def measure_contradictions(declared: list[dict[str, Any]],
                           in_code: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Артефакты, у которых объявлено ДВА срока годности — в конституции и в коде.

    Ось не выводится из двух первых: оба порога могут иметь запас к такту и всё
    равно расходиться между собой.

    **Расхождение само по себе НЕ есть дефект, и выдавать его за дефект было бы
    ровно той ложью, против которой прибор написан.** Два числа отвечают на два
    вопроса: ``slo_hours`` — «просрочен ли артефакт для флота», порог в коде —
    «годен ли он для ЭТОГО решения». Второй вправе быть строже первого
    (``kill_switch`` отказывается судить по красным флагам старше получаса при
    флотском сроке 3 ч — это осторожность, а не спор) и вправе быть мягче
    (публичная поверхность живёт две недели при суточном снимке).

    Вред — в том, что у артефакта ДВА срока и ни один не назван главным: сторож
    свежести флота зелен, пока решение уже отказывает, и наоборот. Острый
    подслучай — когда порог в коде оказывается НИЖЕ такта: тогда он красен по
    построению независимо от того, какой из двух сроков главный.
    """
    declared_by_artifact: dict[str, list[dict[str, Any]]] = {}
    for row in declared:
        if row["verdict"] == "unit_undeclared":
            continue
        declared_by_artifact.setdefault(row["artifact"], []).append(row)

    rows: list[dict[str, Any]] = []
    for row in in_code:
        if row["threshold_hours"] is None or not row.get("artifact"):
            continue
        for other in declared_by_artifact.get(row["artifact"], []):
            if float(other["threshold_hours"]) == float(row["threshold_hours"]):
                continue
            rows.append({
                "artifact": row["artifact"],
                "module": row["module"],
                "constant": row["constant"],
                "code_hours": row["threshold_hours"],
                "declared_hours": float(other["threshold_hours"]),
                "where": other["where"],
                "tact_hours": row["tact_hours"],
                "ratio": (float(other["threshold_hours"]) / row["threshold_hours"]
                          if row["threshold_hours"] else None),
            })
    return rows


# ---------------------------------------------------------------------------
# Сводный замер и отчёт
# ---------------------------------------------------------------------------

#: Исходы, которые ЕСТЬ НАХОДКА класса.
FINDING_VERDICTS = ("below_tact", "no_margin")

#: Исходы, которые есть ТРЕТИЙ ИСХОД: не «с запасом» и не находка.
UNMEASURED_VERDICTS = ("tact_unknown", "unit_undeclared", "subject_ambiguous",
                       "subject_not_declared", "file_unparsed")


def measure(root: Path | str | None = None) -> dict[str, Any]:
    """Полный замер класса: обе формы и ось противоречия.

    ``root`` — дерево, из которого мерим. По умолчанию — дерево, из которого
    исполняется САМ прибор: предмет здесь КОД и КОНСТИТУЦИЯ, у них нет такта и
    нет срока годности, поэтому мерить надо то дерево, откуда прибор запущен
    (та же развилка, что у `ADR-559`/`ADR-561`).
    """
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    manifest = load_constitution(base)
    table = artifact_tacts(manifest)
    declared = measure_declared(table)
    in_code = measure_in_code(base, table)
    contradictions = measure_contradictions(declared, in_code)
    return {
        "applied": APPLIED,
        "root": str(base),
        "artifacts": len(table),
        "declared": declared,
        "in_code": in_code,
        "contradictions": contradictions,
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[row["verdict"]] = out.get(row["verdict"], 0) + 1
    return out


def format_report(result: dict[str, Any]) -> str:
    """Отчёт для шага 0-офис. Третий исход печатается ПЕРВЫМ."""
    lines: list[str] = []
    declared = result["declared"]
    in_code = result["in_code"]
    dc = _counts(declared)
    cc = _counts(in_code)

    population_code = sum(count for verdict, count in cc.items()
                          if verdict != "outside_population")
    unmeasured = (sum(dc.get(v, 0) for v in UNMEASURED_VERDICTS)
                  + sum(cc.get(v, 0) for v in UNMEASURED_VERDICTS))
    findings = (sum(dc.get(v, 0) for v in FINDING_VERDICTS)
                + sum(cc.get(v, 0) for v in FINDING_VERDICTS))

    lines.append(
        f"порог сенсора против такта предмета (заказ G146 п. 2): НЕ ИЗМЕРЕНО "
        f"{unmeasured} · находок {findings} · население {len(declared)} объявленных "
        f"порогов + {population_code} в коде (артефактов конституции "
        f"{result['artifacts']})")

    lines.append(
        "  объявленная форма: " + " · ".join(
            f"{verdict} {count}" for verdict, count in sorted(dc.items())))
    lines.append(
        "  в коде: " + " · ".join(
            f"{verdict} {count}" for verdict, count in sorted(cc.items())
            if verdict != "outside_population")
        + f" | вне населения {cc.get('outside_population', 0)} (порог сравнивается "
          f"не с возрастом производимого — таймаут сети, срок кэша в памяти)")

    for row in declared:
        if row["verdict"] in FINDING_VERDICTS:
            lines.append(f"  [{row['verdict']}] объявлено: {row['artifact']} "
                         f"{row['where']} — {row['reason']}")
    for row in in_code:
        if row["verdict"] in FINDING_VERDICTS:
            lines.append(f"  [{row['verdict']}] в коде: {row['module']}:"
                         f"{row['constant']} → {row['artifact']} — {row['reason']}")

    for row in result["contradictions"]:
        ratio = f"×{row['ratio']:.3g}" if row["ratio"] else "—"
        sharp = (row["tact_hours"] is not None
                 and row["code_hours"] < row["tact_hours"])
        lines.append(
            f"  [два срока{', ОСТРЫЙ' if sharp else ''}] {row['artifact']}: "
            f"конституция {row['declared_hours']:.3g} ч ({row['where']}) против "
            f"{row['constant']}={row['code_hours']:.3g} ч "
            f"({row['module']}) — {ratio}")

    not_declared = [row for row in in_code
                    if row["verdict"] == "subject_not_declared"]
    if not_declared:
        lines.append(
            f"  [{NOT_MEASURED}] у {len(not_declared)} сторож(ей) предмет такта НЕ "
            f"объявлен в конституции — порог не способен проверить никто: "
            + ", ".join(f"{row['module']}:{row['constant']}"
                        for row in not_declared[:4])
            + (" …" if len(not_declared) > 4 else ""))
    for verdict in ("tact_unknown", "unit_undeclared", "subject_ambiguous",
                    "file_unparsed"):
        rows = [row for row in declared + in_code if row["verdict"] == verdict]
        if rows:
            lines.append(f"  [{NOT_MEASURED}] {verdict} {len(rows)}: "
                         + ", ".join(
                             f"{row.get('module') or row.get('artifact')}"
                             f":{row.get('constant') or row.get('where')}"
                             for row in rows[:4])
                         + (" …" if len(rows) > 4 else ""))

    if result["contradictions"]:
        lines.append(
            f"  «два срока» ({len(result['contradictions'])}) сам по себе НЕ дефект: "
            f"порог решения вправе быть строже флотского SLO. Вред — что главным не "
            f"назван ни один; острым помечен тот, где порог в коде НИЖЕ такта")
    lines.append(
        "  НЕ ДОКЛАДЫВАЕТ: НАБЛЮДЁННЫЙ такт (все такты объявленные — артефакт, "
        "который пишут чаще расписания, держится на незаявленном писателе) · "
        "исполняется ли сравнение (дорога есть достижимость) · каким порог ДОЛЖЕН "
        "быть (это замер разрывов писателя, а не чтение)")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None,
                        help="дерево замера (по умолчанию — дерево прибора)")
    parser.add_argument("--json", action="store_true", help="полный замер в JSON")
    args = parser.parse_args(argv)
    try:
        result = measure(args.root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[{NOT_MEASURED}] замер не выполнен: {type(exc).__name__}: {exc}")
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(format_report(result))
    findings = (sum(1 for row in result["declared"]
                    if row["verdict"] in FINDING_VERDICTS)
                + sum(1 for row in result["in_code"]
                      if row["verdict"] in FINDING_VERDICTS)
                + len(result["contradictions"]))
    return 1 if findings else 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
