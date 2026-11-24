#!/usr/bin/env python3
"""Сколько правил аудита объявляют, что ПРОПУСКАЮТ тесты, а спрашивают ИМЯ файла.

Класс найден 24.11 (цикл #1234, ADR-1088, карточка
``inbox-pravilo-atomic-writes-obyavlyaet-propusk``) и до этого прибора не был измерен
нигде. Форма такая: правило объявляет у двери ``_iter_py_files(skip_tests=True)``, то
есть утверждает «тесты я не смотрю», а дверь решает вопрос ``fname.startswith("test_")``
— то есть отвечает про ИМЯ, а не про МЕСТО. Соврать она может в ОБЕ стороны:

* помощник, живущий в каталоге тестов и названный иначе (``_mtime_clock_door.py``,
  ``_hermetic_launchd.py``, ``_freshness.py`` …), **СКАНИРУЕТСЯ** как продукционный код;
* файл ``test_*.py``, лежащий ВНЕ каталога тестов, **ПРОПУСКАЕТСЯ**, хотя продукционным
  кодом он как раз может быть.

**Цена первой стороны ИЗМЕРЕНА на настоящей аварии, а не предположена.** Замер на
вершине ``cd9610c40`` (состояние ``main`` ДО ADR-1088): правило ``atomic_writes``
доложило **7** нарушений при потолке храповика 5 — ``main`` был красным, — и **2** из
семи были ДВЕ СТРОКИ ТЕКСТА внутри исходника плагина, который прибор
``spa_core/tests/_mtime_clock_door.py`` выкладывает в одноразовое дерево. Спроси дверь о
МЕСТЕ — и те два исчезают, а остальные пять остаются: тот же красный ``main`` закрывался
и этой стороной, независимо от починки «зов против текста».

**Сегодня расхождение вердикта РАВНО НУЛЮ, и это не повод считать класс пустым.**
ADR-1088 научил правило спрашивать токенами, поэтому текст внутри литерала нарушением
уже не считается, и те же 64 помощника сегодня вердикта не меняют. Но «красен сегодня
мерой класса НЕ является» (``.claude/rules/deployment.md`` § девятая дверь, п. 5):
предмет ADR-897 был зелёным все восемь дней до взрыва. Поэтому перепись мерит НАСЕЛЕНИЕ
(сколько файлов стоят в области правила ошибочно) ОТДЕЛЬНО от РАСХОЖДЕНИЯ ВЕРДИКТА
(сколько нарушений от этого меняется), и ноль во втором не вычитается из первого.

**Форма двери спрашивается у ПОВЕДЕНИЯ, а не у исходника.** Прибор кладёт в
одноразовое дерево два файла — ``tests/_helper.py`` (место есть, имени нет) и
``pkg/test_thing.py`` (имя есть, места нет) — и смотрит, кого дверь отдаст при
``skip_tests=True``. Разбор прозы ответил бы на вопрос «как это написано», а нужен
ответ «что это делает»: ровно на этой подмене стоял исходный дефект, где докстринг
обещал пропуск тестов, а код спрашивал имя (и ровно так же ошиблась мерка #1234 —
«в строке ЕСТЬ литерал» вместо «совпадение ВНУТРИ литерала», G1074 п. 4).

**Поверхность берётся из ОБЪЯВЛЕНИЯ, а не из головы.** Правила — это имена из
``AUDIT_RULES``, а пара «имя правила → метод» читается из САМОГО аудита (список
``checks`` в его ``main()``, разбор по AST). Перечислять методы по совпадению имени
``check_*`` значило бы мерить имя метода вместо объявления — дословно урок #1218
(«имя метода мерой НЕ является»: 547 зовов ``ast.walk`` вошли в «поверхность»
перечисления каталогов, которых не перечисляли вовсе).

**Замер поверхности сразу назвал соседа, которого заказ не ждал.** Объявлено правил
**семь**, пар «имя → метод» в аудите **пять**: ``no_llm_in_analytics`` и
``no_print_in_modules`` объявлены в ``AUDIT_RULES`` и не реализованы НИГДЕ — ни метода,
ни упоминания за пределами самого списка. Такое правило не может ни найти нарушение, ни
сказать, что не умеет: оно печатается в отчёте нулём наравне с правилом, которое
действительно прошло по дереву. Для вопроса этой переписи они — ``UNMEASURED`` с
названной причиной, а не «вне предмета».

**Исходы различимы у каждого правила (инв. #17):**

* ``DOOR_PLACE``   — спрашивает через общую дверь, и дверь отвечает о МЕСТЕ (норма);
* ``DOOR_NAME``    — спрашивает через общую дверь, а дверь отвечает об ИМЕНИ (ПРЕДМЕТ);
* ``OWN_FORM``     — спрашивает САМО, минуя дверь (другой сайт, назван вслух);
* ``NO_QUESTION``  — вопроса «это тест?» не задаёт вовсе, вне предмета;
* ``UNMEASURED``   — правило объявлено и не реализовано · метода нет · не разобрано.

«НЕ ИЗМЕРЕНО» никогда не выдаётся за «чисто»: нереализованное правило — это отказ с
причиной, а не вычитание из населения.

**Чего перепись НЕ закрывает (названо вслух, чтобы не читалось шире).** Она судит ОДНУ
дверь одного модуля — ``spa_core/analytics/architecture_audit.py``. Любая другая мера,
решающая «это тест?» по имени файла (сборщики поверхностей, храповики, пушеры),
этой мерой НЕ судится, и **население класса за пределами аудита НЕ ИЗМЕРЕНО** — нулём
это не считается. Расхождение вердикта мерится на ТЕКУЩЕМ дереве: правило, чьё
расхождение родится от будущей правки, сегодня честно даст ноль. И перепись ничего не
чинит — она только ЧИТАЕТ.

**Коды возврата различают ЧЕТЫРЕ исхода, и это не роскошь.** Если бы «правило объявлено
и не реализовано» давало код «НЕ ИЗМЕРЕНО», перепись отвечала бы кодом 2 ВСЕГДА (таких
правил два с первого же замера) — и вердикт о предмете перестал бы читаться вовсе, то
есть постоянный код 2 был бы ровно так же бесполезен, как постоянный ноль:

* **0** — предмет ПУСТ и о КАЖДОМ объявленном правиле вопрос задать удалось;
* **1** — предмет НЕ ПУСТ: правило спрашивает дверь, отвечающую об ИМЕНИ (находка);
* **2** — перепись НЕ СМОГЛА задать свой вопрос (модуля нет · ``AUDIT_RULES`` не
  разобран · форма двери не измерена) — с названной причиной;
* **3** — предмет пуст, но у N объявленных правил вопрос задать НЕЧЕМ (названный долг).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

AUDIT_MODULE_PATH = Path("spa_core/analytics/architecture_audit.py")

#: Исходы классификации правила. Порядок — от нормы к находке.
#:
#: ``DECLARED_ABSENT`` добавлен 2026-11-24 (ADR-1091) и это УСИЛЕНИЕ, а не
#: послабление: прежде «правило объявлено и не реализовано» и «правило
#: объявлено, не реализовано И долг НАЗВАН с причиной» давали один исход
#: ``UNMEASURED``, то есть перепись не умела отличить молчаливую дыру от
#: признанного долга. Молчаливая дыра по-прежнему даёт ``UNMEASURED`` и код 3;
#: ``DECLARED_ABSENT`` требует ОБЪЯВЛЕНИЯ в ``RULE_NOT_IMPLEMENTED`` аудита И
#: непустой причины при нём — объявление без причины остаётся ``UNMEASURED``.
VERDICTS = (
    "DOOR_PLACE",
    "DOOR_NAME",
    "OWN_FORM",
    "NO_QUESTION",
    "DECLARED_ABSENT",
    "UNMEASURED",
)

#: Исходы вопроса «о чём отвечает дверь» — спрашиваются у ПОВЕДЕНИЯ.
DOOR_FORMS = ("PLACE_AND_NAME", "PLACE_ONLY", "NAME_ONLY", "NEITHER", "UNMEASURED")


class NotMeasured(Exception):
    """Перепись не смогла задать свой вопрос — причина обязательна."""


@dataclass
class RuleRow:
    rule: str
    verdict: str
    reason: str
    method: str | None = None
    skip_tests_calls: int = 0


@dataclass
class Census:
    repo_root: str
    audit_module: str
    door_form: str
    door_form_reason: str
    declared_rules: list[str] = field(default_factory=list)
    rows: list[RuleRow] = field(default_factory=list)
    # население: файлы, стоящие в области правила ошибочно
    misplaced_files: list[str] = field(default_factory=list)
    misplaced_write_calls: list[str] = field(default_factory=list)
    name_only_outside_tests: list[str] = field(default_factory=list)
    # расхождение вердикта на ТЕКУЩЕМ дереве
    verdict_divergence: dict[str, Any] = field(default_factory=dict)

    @property
    def subject(self) -> list[RuleRow]:
        return [r for r in self.rows if r.verdict == "DOOR_NAME"]

    @property
    def unmeasured(self) -> list[RuleRow]:
        return [r for r in self.rows if r.verdict == "UNMEASURED"]


# ── Поверхность: объявление правил и пара «имя правила → метод» ───────────────


def declared_rules(source: str) -> list[str]:
    """Имена правил из ``AUDIT_RULES`` — ОБЪЯВЛЕНИЕ, а не обход методов."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "AUDIT_RULES" not in names:
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            raise NotMeasured("AUDIT_RULES объявлен не списком — состав не разобран")
        out = []
        for elt in node.value.elts:
            if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
                raise NotMeasured("в AUDIT_RULES есть не-строковый элемент")
            out.append(elt.value)
        return out
    raise NotMeasured("AUDIT_RULES в модуле аудита не найден")


def rule_to_method(source: str) -> dict[str, str]:
    """Пара «имя правила → имя метода», прочитанная у САМОГО аудита.

    Ищутся кортежи вида ``("rule_name", <что-то>.check_xxx)`` где угодно в модуле: это
    и есть то место, где аудит сам говорит, какой метод исполняет какое правило.
    Совпадение по имени метода (``check_*``) здесь НЕ используется намеренно — имя
    метода объявлением не является.
    """
    tree = ast.parse(source)
    pairs: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
            continue
        head, tail = node.elts
        if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
            continue
        if not isinstance(tail, ast.Attribute):
            continue
        pairs[head.value] = tail.attr
    if not pairs:
        raise NotMeasured(
            "ни одной пары «имя правила → метод» в модуле аудита не разобрано"
        )
    return pairs


def declared_not_implemented(source: str) -> dict[str, str]:
    """Правила, ОБЪЯВЛЕННЫЕ аудитом как не исполняемые, вместе с причиной.

    Читается ``RULE_NOT_IMPLEMENTED`` по AST — объявление, а не догадка. Пункт
    без причины (пустая строка, не-строковое значение) объявлением НЕ
    считается: «названный долг» без имени причины неотличим от молчаливой
    дыры, а именно их различение и есть предмет. Отсутствие самого словаря —
    не ошибка: до ADR-1091 его не было вовсе, и тогда исход у правила без
    метода остаётся ``UNMEASURED``.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if "RULE_NOT_IMPLEMENTED" not in names:
            continue
        if not isinstance(node.value, ast.Dict):
            raise NotMeasured(
                "RULE_NOT_IMPLEMENTED объявлен не словарём — состав не разобран"
            )
        # Имя `found`, а не `out`: сцена пробы ломает перепись заменой
        # УНИКАЛЬНОГО якоря `        return out\n` в `declared_rules`, и второе
        # такое же место сделало бы якорь неоднозначным — то есть сцена
        # перестала бы строиться (ГРОМКИЙ отказ, но на ровном месте).
        found: dict[str, str] = {}
        for key, value in zip(node.value.keys, node.value.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                raise NotMeasured("в RULE_NOT_IMPLEMENTED есть не-строковый ключ")
            try:
                reason = ast.literal_eval(value)
            except (ValueError, SyntaxError, TypeError):
                reason = None
            if isinstance(reason, str) and reason.strip():
                found[key.value] = reason
        return found
    return {}


def skip_tests_calls_in(source: str, method: str) -> int:
    """Сколько раз метод зовёт общую дверь с НЕложным ``skip_tests``."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != method:
            continue
        count = 0
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            attr = func.attr if isinstance(func, ast.Attribute) else None
            if attr != "_iter_py_files":
                continue
            for kw in call.keywords:
                if kw.arg != "skip_tests":
                    continue
                if isinstance(kw.value, ast.Constant) and not kw.value.value:
                    continue
                count += 1
        return count
    raise NotMeasured(f"метода {method}() в модуле аудита нет")


def own_name_form(source: str, method: str) -> str | None:
    """Назвать форму, которой метод спрашивает «это тест?» САМ, минуя дверь.

    Спрашивается ТОЛЬКО ЗОВ (аргумент ``glob``/``rglob``), а не любая строка в теле
    метода. Первая редакция этой мерки искала литерал ``test_*`` где угодно и зачла за
    форму ДОКСТРИНГ, который про тесты всего лишь рассказывает, — ровно тот дефект,
    против которого написана вся перепись (и дословно дефект мерки #1234, G1074 п. 4:
    «в строке ЕСТЬ литерал» ≠ «совпадение ВНУТРИ литерала»).
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != method:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            attr = func.attr if isinstance(func, ast.Attribute) else None
            if attr not in {"glob", "rglob"}:
                continue
            for arg in sub.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if "test" in arg.value:
                        return f"{attr}({arg.value!r})"
        return None
    raise NotMeasured(f"метода {method}() в модуле аудита нет")


# ── Форма двери: спрашивается у ПОВЕДЕНИЯ ────────────────────────────────────


def measure_door_form(audit_cls) -> tuple[str, str]:
    """Положить два файла и спросить дверь, кого она отдаст при ``skip_tests=True``.

    ``tests/_helper.py`` — место есть, имени нет; ``pkg/test_thing.py`` — имя есть,
    места нет. Исходы различимы, и ни один не выводится из текста модуля.
    """
    with tempfile.TemporaryDirectory(prefix="spa_door_form_") as tmp:
        root = Path(tmp)
        (root / "tests").mkdir()
        (root / "pkg").mkdir()
        by_place = root / "tests" / "_helper.py"
        by_name = root / "pkg" / "test_thing.py"
        plain = root / "pkg" / "module.py"
        for p in (by_place, by_name, plain):
            p.write_text("x = 1\n", encoding="utf-8")

        audit = audit_cls(str(root))
        try:
            yielded = {
                Path(fpath).resolve()
                for fpath, _ in audit._iter_py_files(root, skip_tests=True)
            }
        except Exception as exc:  # noqa: BLE001 — причина обязана быть названа
            return "UNMEASURED", f"дверь подняла {type(exc).__name__}: {exc}"

        if plain.resolve() not in yielded:
            return (
                "UNMEASURED",
                "дверь не отдала обычный модуль — сцена не воспроизводит обход",
            )
        place_skipped = by_place.resolve() not in yielded
        name_skipped = by_name.resolve() not in yielded

    if place_skipped and name_skipped:
        return "PLACE_AND_NAME", "пропущены и помощник в tests/, и файл test_*.py вне tests/"
    if place_skipped:
        return "PLACE_ONLY", "пропущен только помощник в tests/"
    if name_skipped:
        return (
            "NAME_ONLY",
            "пропущен только файл test_*.py; помощник в tests/ СКАНИРУЕТСЯ — предмет класса",
        )
    return "NEITHER", "не пропущено ни одно из двух — skip_tests не действует вовсе"


# ── Население: файлы, стоящие в области правила ошибочно ─────────────────────


def _write_mode(call: ast.Call) -> str | None:
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    if isinstance(mode, str) and any(ch in mode for ch in "wxa"):
        return mode
    return None


def measure_population(base_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """Население ОБЕИХ сторон лжи + живое топливо первой из них.

    Возвращает (помощники в tests/ с именем не ``test_*``, зовы ``open`` с пишущим
    режимом в них, файлы ``test_*.py`` ВНЕ каталога тестов).
    """
    by_name: set[Path] = set()
    by_place: set[Path] = set()
    for dirpath, dirs, files in os.walk(base_dir):
        dirs[:] = sorted(
            d for d in dirs if d != "__pycache__" and not d.startswith(".")
        )
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            path = Path(dirpath) / fname
            rel = path.relative_to(base_dir)
            if fname.startswith("test_"):
                by_name.add(path)
            if "tests" in rel.parent.parts:
                by_place.add(path)

    misplaced = sorted(by_place - by_name)
    name_outside = sorted(by_name - by_place)

    write_calls: list[str] = []
    for path in misplaced:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            write_calls.append(f"{path}: НЕ РАЗОБРАН (SyntaxError)")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else None)
            )
            if name != "open":
                continue
            mode = _write_mode(node)
            if mode is not None:
                write_calls.append(f"{path}:{node.lineno} open(..., {mode!r})")

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(_REPO_ROOT))
        except ValueError:
            return str(p)

    return [_rel(p) for p in misplaced], write_calls, [_rel(p) for p in name_outside]


# ── Расхождение вердикта: тот же вопрос, две формы пропуска ──────────────────


def measure_verdict_divergence(audit_module, rule_methods: dict[str, str]) -> dict[str, Any]:
    """Прогнать правила дважды — живой дверью и дверью «пропуск ТОЛЬКО по имени».

    Расхождение считается на ТЕКУЩЕМ дереве. Ноль здесь — наблюдение, а не молчание:
    он означает, что сегодня ни одно лишнее нарушение не доезжает до вердикта.
    """
    audit_cls = audit_module.ArchitectureAudit
    original = audit_cls._iter_py_files

    def name_only(self, root, skip_tests=False, skip_pycache=True):
        for fpath, lines in original(self, root, skip_tests=False, skip_pycache=skip_pycache):
            if skip_tests and Path(fpath).name.startswith("test_"):
                continue
            yield fpath, lines

    def collect() -> set[tuple[str, str, int]]:
        audit = audit_cls("spa_core")
        found: set[tuple[str, str, int]] = set()
        for rule, method in sorted(rule_methods.items()):
            fn = getattr(audit, method, None)
            if fn is None:
                continue
            for v in fn():
                found.add((rule, v.file, v.line))
        return found

    live = collect()
    audit_cls._iter_py_files = name_only
    try:
        legacy = collect()
    finally:
        audit_cls._iter_py_files = original

    gone = sorted(legacy - live)
    came = sorted(live - legacy)
    return {
        "live_total": len(live),
        "name_only_total": len(legacy),
        "disappears_when_place_is_asked": [list(x) for x in gone],
        "appears_when_place_is_asked": [list(x) for x in came],
    }


# ── Сборка ───────────────────────────────────────────────────────────────────


def run(repo_root: Path) -> Census:
    module_path = repo_root / AUDIT_MODULE_PATH
    if not module_path.is_file():
        raise NotMeasured(f"модуля аудита нет по пути {module_path}")
    source = module_path.read_text(encoding="utf-8", errors="replace")

    rules = declared_rules(source)
    pairs = rule_to_method(source)
    not_implemented = declared_not_implemented(source)

    import importlib

    audit_module = importlib.import_module("spa_core.analytics.architecture_audit")
    door_form, door_reason = measure_door_form(audit_module.ArchitectureAudit)

    census = Census(
        repo_root=str(repo_root),
        audit_module=str(AUDIT_MODULE_PATH),
        door_form=door_form,
        door_form_reason=door_reason,
        declared_rules=rules,
    )

    for rule in rules:
        method = pairs.get(rule)
        if method is None:
            declared_reason = not_implemented.get(rule)
            if declared_reason:
                census.rows.append(
                    RuleRow(
                        rule=rule,
                        verdict="DECLARED_ABSENT",
                        reason=(
                            "правило ОБЪЯВЛЕНО не исполняемым в "
                            "RULE_NOT_IMPLEMENTED, причина НАЗВАНА — долг "
                            "названный, а не молчаливая дыра; двери «это "
                            f"тест?» не задаёт вовсе. Причина: {declared_reason}"
                        ),
                    )
                )
            else:
                census.rows.append(
                    RuleRow(
                        rule=rule,
                        verdict="UNMEASURED",
                        reason=(
                            "правило ОБЪЯВЛЕНО в AUDIT_RULES и НЕ РЕАЛИЗОВАНО: "
                            "пары «имя → метод» у аудита нет, и в "
                            "RULE_NOT_IMPLEMENTED причина не названа — "
                            "нарушение найти нечем и долг не назван"
                        ),
                    )
                )
            continue
        try:
            calls = skip_tests_calls_in(source, method)
        except NotMeasured as exc:
            census.rows.append(
                RuleRow(rule=rule, verdict="UNMEASURED", reason=str(exc), method=method)
            )
            continue

        if calls:
            if door_form == "UNMEASURED":
                # Форма двери не снята ⇒ о правиле, которое её зовёт, сказать нечего.
                # Подставить «отвечает о МЕСТЕ» значило бы выдать неизмеренное за норму.
                verdict, reason = "UNMEASURED", (
                    f"зовёт общую дверь ({calls} зов/а), но форма двери НЕ ИЗМЕРЕНА: "
                    f"{door_reason}"
                )
            elif door_form in {"NAME_ONLY", "NEITHER"}:
                verdict, reason = "DOOR_NAME", (
                    f"зовёт общую дверь с skip_tests ({calls} зов/а); дверь: {door_form}"
                )
            else:
                verdict, reason = "DOOR_PLACE", (
                    f"зовёт общую дверь с skip_tests ({calls} зов/а); дверь: {door_form}"
                )
            census.rows.append(
                RuleRow(
                    rule=rule,
                    verdict=verdict,
                    reason=reason,
                    method=method,
                    skip_tests_calls=calls,
                )
            )
            continue

        own = own_name_form(source, method)
        if own is not None:
            census.rows.append(
                RuleRow(
                    rule=rule,
                    verdict="OWN_FORM",
                    reason=(
                        f"спрашивает САМО, минуя дверь: {own!r} — другой сайт того же "
                        "вопроса, в предмет этой переписи не входит"
                    ),
                    method=method,
                )
            )
            continue

        census.rows.append(
            RuleRow(
                rule=rule,
                verdict="NO_QUESTION",
                reason="вопроса «это тест?» не задаёт — вне предмета",
                method=method,
            )
        )

    base_dir = repo_root / "spa_core"
    if not base_dir.is_dir():
        raise NotMeasured(f"каталога {base_dir} нет — население не измерено")
    misplaced, writes, name_outside = measure_population(base_dir)
    census.misplaced_files = misplaced
    census.misplaced_write_calls = writes
    census.name_only_outside_tests = name_outside

    door_rules = {
        row.rule: row.method
        for row in census.rows
        if row.verdict in {"DOOR_NAME", "DOOR_PLACE"} and row.method
    }
    census.verdict_divergence = measure_verdict_divergence(audit_module, door_rules)
    return census


def format_report(census: Census) -> str:
    out: list[str] = []
    out.append(
        "ПЕРЕПИСЬ: кто решает «это тест?» по ИМЕНИ файла "
        f"(дерево {census.repo_root}, модуль {census.audit_module})"
    )
    out.append(
        f"  форма ДВЕРИ (замер ПОВЕДЕНИЯ, не прозы): {census.door_form} — {census.door_form_reason}"
    )
    out.append(f"  объявлено правил: {len(census.declared_rules)}")
    for verdict in VERDICTS:
        rows = [r for r in census.rows if r.verdict == verdict]
        if not rows:
            continue
        out.append(f"  {verdict}: {len(rows)}")
        for row in rows:
            mark = (
                "⚠️" if verdict in {"DOOR_NAME", "UNMEASURED"}
                else ("⬜" if verdict == "DECLARED_ABSENT" else "·")
            )
            out.append(f"     {mark} {row.rule} — {row.reason}")

    out.append("  НАСЕЛЕНИЕ (обе стороны лжи, считается отдельно от вердикта):")
    out.append(
        f"     сторона 1 — помощники в tests/ с именем не test_*, то есть СКАНИРУЮТСЯ: "
        f"{len(census.misplaced_files)}"
    )
    for path in census.misplaced_files[:5]:
        out.append(f"        {path}")
    if len(census.misplaced_files) > 5:
        out.append(f"        … и ещё {len(census.misplaced_files) - 5}")
    out.append(
        f"     живое топливо — зовы open() с пишущим режимом в них: "
        f"{len(census.misplaced_write_calls)}"
    )
    for item in census.misplaced_write_calls:
        out.append(f"        {item}")
    out.append(
        f"     сторона 2 — файлы test_*.py ВНЕ каталога тестов, то есть ПРОПУСКАЮТСЯ: "
        f"{len(census.name_only_outside_tests)}"
    )
    for path in census.name_only_outside_tests[:5]:
        out.append(f"        {path}")

    div = census.verdict_divergence
    out.append("  РАСХОЖДЕНИЕ ВЕРДИКТА на ТЕКУЩЕМ дереве (живая дверь против «только имя»):")
    out.append(
        f"     нарушений живой дверью {div.get('live_total')} · дверью «только имя» "
        f"{div.get('name_only_total')}"
    )
    gone = div.get("disappears_when_place_is_asked") or []
    came = div.get("appears_when_place_is_asked") or []
    out.append(f"     исчезает при вопросе о МЕСТЕ: {len(gone)}")
    for item in gone:
        out.append(f"        - {item}")
    out.append(f"     появляется: {len(came)}")
    for item in came:
        out.append(f"        + {item}")
    if not gone and not came:
        out.append(
            "     ✅ измерено и РАВНО НУЛЮ — но это НЕ пустой класс: население стороны 1 "
            f"= {len(census.misplaced_files)}, и «красен сегодня» мерой класса не является"
        )

    declared_absent = [r for r in census.rows if r.verdict == "DECLARED_ABSENT"]
    if declared_absent:
        out.append(
            f"  ⬜ НАЗВАННЫЙ ДОЛГ: {len(declared_absent)} правил(о/а) объявлены "
            "НЕ исполняемыми с причиной — это третий исход (инв. #17), а не ноль "
            "и не молчаливая дыра"
        )
    if census.unmeasured:
        out.append(
            f"  ⚠️ НЕ ИЗМЕРЕНО: {len(census.unmeasured)} правил(о/а) — причина у каждого названа выше"
        )
    if census.subject:
        out.append(
            f"  ⚠️ ПРЕДМЕТ НЕ ПУСТ: {len(census.subject)} правил(о/а) спрашивают дверь, "
            "которая отвечает об ИМЕНИ"
        )
    else:
        out.append("  ✅ ПРЕДМЕТ ПУСТ: ни одно правило не решает принадлежность к тестам по имени файла")

    out.append(
        "  граница: судится ОДНА дверь ОДНОГО модуля; население класса за пределами "
        "аудита НЕ ИЗМЕРЕНО и нулём не считается"
    )
    out.append("  ADVISORY: прибор только ЧИТАЕТ — ни одно правило не изменено")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="дерево, о котором спрашивается (умолчание ПЕЧАТАЕТСЯ)",
    )
    parser.add_argument("--json", action="store_true", help="отдать документ на stdout")
    args = parser.parse_args(argv)

    # Три исхода у ВХОДА различимы: дерево НАЗВАНО · взято умолчание (печатается) ·
    # названное дерево нечитаемо (отказ ниже). Сверять строку с умолчанием нельзя:
    # названное дерево, СОВПАВШЕЕ с умолчанием, доложилось бы как неназванное.
    repo_root = Path(args.repo_root or _REPO_ROOT).resolve()
    if args.repo_root is None:
        print(
            f"[перепись] дерево НЕ НАЗВАНО входом, взято умолчание: {repo_root}",
            file=sys.stderr,
        )

    try:
        census = run(repo_root)
    except NotMeasured as exc:
        print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = asdict(census)
        payload["rows"] = [asdict(r) for r in census.rows]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_report(census))

    if census.door_form == "UNMEASURED":
        print(
            f"⚠️ НЕ ИЗМЕРЕНО: форма двери не снята — {census.door_form_reason}",
            file=sys.stderr,
        )
        return 2
    if census.subject:
        return 1
    return 3 if census.unmeasured else 0


if __name__ == "__main__":
    raise SystemExit(main())
