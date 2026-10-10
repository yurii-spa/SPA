"""Одно поле, НЕСКОЛЬКО дверей часов — и согласие между ними не проверяет никто.

Заказ **G110 приказа владельца «Portfolio CIO»**, пункт 3 (поставлен ADR-535).

## Вопрос

Дословно: «Сторож разбирает отметку времени только секундной точности. Замерено на
сцене: ``2026-10-02T05:07:31.286040Z`` даёт «метка времени не разобрана» ⇒ вердикт
``unchecked``. Сегодня недостижимо (единственный писатель пишет секунды), поэтому
починка вслепую запрещена. Спросить надо: **есть ли в дереве ВТОРОЙ писатель этого
поля, и мерить у формы записи, а не у имени файла.**»

Заказ прямо запретил чинить дверь вслепую, и прибор её НЕ ЧИНИТ: ни одна строка
``check_undelivered_work._parse_ts`` этой доставкой не меняется. Прибор отвечает на
вопрос заказа и ни на какой другой.

## Почему «имя файла» причиной не является

Ключ ``"ts"`` стои́т в 790 местах 451 файла дерева (замер 09.10): фид APY, кокпит,
оценка ковариации — все зовут своё поле так же. Население по ИМЕНИ КЛЮЧА отвечает
на вопрос «где встречается слово», а не «кто пишет это поле». Поэтому население
берётся по **ФОРМЕ ЗАПИСИ**, и форма объявлена не на вкус: запись обязана несть
отметку ВМЕСТЕ С ТЕМ ключом, который читатель требует рядом с ней
(:data:`SUBJECTS`). Для журнала объявлений это ``session`` — ``session_state``
без него о личности не судит; для карточки это ``claimed_by`` — сторож читает
пару ``claimed_by``/``claimed_at`` одним перечнем (``_CLAIM_KEYS``).

## Ответ на заказ: писатель НЕ ОДИН, и дверь не одна тоже

Посылка «единственный писатель пишет секунды» ИЗМЕРЕННО НЕВЕРНА, причём дважды:

* **производителей формы 10 в 4 файлах** (замер на ``origin/main`` 59aaef0a6), и
  согласие между ними держится на том, что ПЯТЬ независимых копий одного литерала
  ``"%Y-%m-%dT%H:%M:%SZ"`` случайно равны. Связанных с дверью — **ни одной**;
* у поля **пять дверей, и четыре из пяти ШИРЕ** той, которая гейтит взятие карточки.
  ``scripts/orchestrator_cycle_lock.py`` сам пишет запись, про которую его докстринг
  обещает «схема — подмножество записи журнала объявлений, **чтобы session_state
  читала её без переходников**», — и при этом СВОЮ запись читает дверью, которая
  принимает микросекунды, а ``session_state`` их не принимает. Один и тот же текст
  у одного читателя «датирован», у другого «метка не разобрана».

Отсюда и вред, которого заказ ждал: он не в том, что дверь узкая, а в том, что
двери РАЗНЫЕ и расхождение молчит. Узкая дверь отвечает ``unchecked``, а
``unchecked`` — это замок очереди: карточка с ним не берётся (ADR-647 мерил такую
634 цикла). Широкая дверь в то же время докладывает, что всё разобрано.

## Чего прибор НЕ меряет (названо заранее)

* **Форму, а не АДРЕС.** Прибор не утверждает, что каждый производитель формы пишет
  именно в живое поле; он утверждает, что в дереве есть N независимых производителей
  ФОРМЫ этого поля и ни один не связан с дверью. Достижимость адреса — другой вопрос.
* **Принимает ли дверь, а не ИСПОЛНЯЕТСЯ ли она.** Дверь зовётся настоящим вызовом на
  закрытом словаре форм; что ветка с этим вызовом когда-либо исполнялась на живой
  записи, прибор не утверждает.
* **Какой дверь ДОЛЖНА быть.** Это замер расхождения, а не предложение порога:
  сузить широкие или расширить узкую — решение, и его цена ни тем, ни другим
  замером здесь не считается.
* **Соседи по предмету НЕ дублируются.** ``artifact_stamp_clock_doors`` (ADR-562) и
  ``python_reader_clock_doors`` (ADR-414) меряют, доходит ли инъекция часов до
  ЗАПИСИ отметки, то есть дверь ПИСАТЕЛЯ. Здесь предмет обратный — какие ТЕКСТОВЫЕ
  формы принимает дверь ЧИТАТЕЛЯ и согласны ли читатели одного поля между собой.
  Ни одного числа соседей прибор не пересчитывает (ADR-220).
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "announce_clock_door_census.json"
ORDER = ("G110 п. 3 (ADR-535) — есть ли ВТОРОЙ писатель отметки, которую разбирает "
         "сторож захвата; мерить у ФОРМЫ записи, а не у имени файла")

STATUS_DOORS_DISAGREE = "CLOCK_DOORS_DISAGREE"
STATUS_DOORS_AGREE = "CLOCK_DOORS_AGREE"
STATUS_UNMEASURED = "UNMEASURED"

#: ДВЕРЬ-ЭТАЛОН: та, которая гейтит взятие карточки (шаги 0a/0b протокола).
#: Остальные двери сравниваются с НЕЙ, потому что её отказ стоит дороже всех —
#: `unchecked` не даёт взять карточку вовсе.
GUARD_DOOR = ("scripts/check_undelivered_work.py", "_parse_ts")

#: Предметы замера: поле отметки + ключ, который читатель требует РЯДОМ с ним.
#: Companion-ключ и есть «форма записи»: он берётся у требования ЧИТАТЕЛЯ, а не
#: из удобства. `session` — без него `session_state` о личности не судит;
#: `claimed_by` — сторож читает пару захвата одним перечнем `_CLAIM_KEYS`.
SUBJECTS: Dict[str, Tuple[str, str]] = {
    "announce_ts": ("ts", "session"),
    "card_claimed_at": ("claimed_at", "claimed_by"),
}

#: Момент-якорь замера. Микросекунды здесь ОБЯЗАТЕЛЬНЫ: ровно этой долей
#: отличается форма, на которой заказ измерил отказ двери. Литерал — сам предмет
#: (пример из ADR-535 п. 3), а не фикстура свежести.
ANCHOR = datetime(2026, 10, 2, 5, 7, 31, 286040, tzinfo=timezone.utc)

#: Закрытый словарь ФОРМ отметки. Перечень закрыт намеренно: «похоже на дату»
#: измерением не является, а доля принятых форм обязана считаться от объявленного
#: знаменателя, а не от того, сколько форм пришло в голову.
FORM_NAMES: Tuple[str, ...] = (
    "seconds_z", "micros_z", "isoformat_offset", "isoformat_sec_offset",
    "naive_seconds", "space_separator", "epoch_float",
)

#: Форма, по которой узнаётся дверь ИМЕННО ЭТОГО поля: её пишут все наблюдаемые
#: производители, и дверь, отказывающая даже ей, разбирает не это поле.
CANONICAL_FORM = "seconds_z"

#: Классы двери относительно эталона. Перечень ЗАКРЫТ.
DOOR_AGREES = "agrees_with_guard"
DOOR_WIDER = "wider_than_guard"
DOOR_NARROWER = "narrower_than_guard"
DOOR_CROSSING = "crossing_guard"
DOOR_FOREIGN = "not_this_field"
DOOR_UNMEASURED = "unmeasured"
DOOR_CLASSES: Tuple[str, ...] = (DOOR_AGREES, DOOR_WIDER, DOOR_NARROWER,
                                 DOOR_CROSSING, DOOR_FOREIGN, DOOR_UNMEASURED)

#: Классы производителя значения. Перечень ЗАКРЫТ.
WRITER_PRODUCES = "produces_form"
WRITER_RELAYS = "relays_read_value"
WRITER_LITERAL = "literal_value"
WRITER_UNMEASURED = "unmeasured"
WRITER_CLASSES: Tuple[str, ...] = (WRITER_PRODUCES, WRITER_RELAYS,
                                   WRITER_LITERAL, WRITER_UNMEASURED)

#: Вердикт двери на одной форме. Перечень ЗАКРЫТ.
V_ACCEPT, V_REFUSE, V_RAISED, V_UNMEASURED = "accepted", "refused", "raised", "unmeasured"

#: Каталоги дерева, в которых ищется население. Объявлены литералом: «весь
#: репозиторий» зависело бы от того, что лежит рядом с деревом.
ROOTS: Tuple[str, ...] = ("spa_core", "scripts", "tests", "studio_shell", "research")

#: Имя журнала объявлений и имена читателей его схемы — по ним выводится население
#: КАНДИДАТОВ-читателей. Правило намеренно ГРУБОЕ: ошибаться обязано в сторону
#: находки, а лишний кандидат отсеивается замером (`not_this_field`), не догадкой.
JOURNAL_FILENAME = "session_changes.jsonl"
SCHEMA_READER_NAMES: Tuple[str, ...] = ("read_entries", "session_state")

#: Предел раскрытия выражения отметки. Назван числом: «раскрывать до конца» на
#: взаимно рекурсивных помощниках не заканчивается никогда.
RESOLVE_DEPTH = 6

#: Служебные ключи строки оси B: узел формата и словари файла едут рядом со
#: строкой, но в артефакт НЕ попадают (узел AST не сериализуем). Имена объявлены
#: здесь, чтобы снятие было ровно одной операцией и не разошлось с установкой.
ROW_FMT_NODE = "_fmt_node"
ROW_CONSTS = "_consts"
ROW_PRIVATE: Tuple[str, ...] = (ROW_FMT_NODE, ROW_CONSTS, "_helpers_file")

_PARSE_ATTRS = frozenset({"strptime", "fromisoformat"})
_READ_ATTRS = frozenset({"get", "group"})


# ───────────────────────────── словарь форм ─────────────────────────────────

def forms_at(anchor: Optional[datetime] = None) -> Dict[str, Any]:
    """Закрытый словарь форм, построенный от ОДНОГО момента.

    Момент — ВХОД, а не стенные часы: иначе прибор мерил бы календарь машины.
    ``epoch_float`` в словаре не ради полноты: значение, не являющееся строкой,
    обязано иметь свой исход — дверь, принимающая число, читает не отметку.
    """
    a = anchor or ANCHOR
    out = {
        "seconds_z": a.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "micros_z": a.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "isoformat_offset": a.isoformat(),
        "isoformat_sec_offset": a.isoformat(timespec="seconds"),
        "naive_seconds": a.strftime("%Y-%m-%dT%H:%M:%S"),
        "space_separator": a.strftime("%Y-%m-%d %H:%M:%SZ"),
        "epoch_float": a.timestamp(),
    }
    missing = [n for n in FORM_NAMES if n not in out]
    extra = [n for n in out if n not in FORM_NAMES]
    if missing or extra:  # pragma: no cover — защита от расхождения перечня и сборки
        raise AssertionError(
            f"словарь форм расходится с объявленным перечнем: нет {missing}, лишние {extra}")
    return out


# ──────────────────────── ось A: двери поля по ИСХОДУ ───────────────────────

def _load_by_path(path: Path, label: str):
    """Модуль двери, загруженный так, КАК ЕГО ГРУЖАЕТ его собственный потребитель.

    Файл внутри пакета грузится ИМЕНЕМ ПАКЕТА (``importlib.import_module``), а не
    по пути: у пакетного модуля относительные импорты, и загрузка по пути рвёт их
    на ``AttributeError: 'NoneType' object has no attribute '__dict__'``. Замерено
    на этой же правке: по пути НЕ ИЗМЕРЕНЫ были 4 двери из 9 — и это была бы
    слабость ПРИБОРА, выданная за свойство дерева. Скрипт вне пакета (``scripts/``)
    грузится по пути — его так зовёт и шаг 0a.
    """
    parts = path.with_suffix("").parts
    if "spa_core" in parts:
        dotted = ".".join(parts[parts.index("spa_core"):])
        return importlib.import_module(dotted)
    spec = importlib.util.spec_from_file_location(label, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"не собран спек модуля для {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_files(repo_root: Path, *, roots: Sequence[str] = ROOTS) -> List[Path]:
    """Питоньи файлы объявленных каталогов + корневые. Порядок устойчив."""
    out: List[Path] = []
    for name in roots:
        base = repo_root / name
        if base.is_dir():
            out.extend(sorted(base.rglob("*.py")))
    out.extend(sorted(repo_root.glob("*.py")))
    return out


def is_test_path(path: Path) -> bool:
    """Роль файла. Сцена теста — тоже производитель формы, но НЕ писатель живого поля,
    и складывать их в одно число нельзя: тестов в дереве кратно больше."""
    text = path.as_posix()
    return path.name.startswith("test_") or "/tests/" in text


def door_candidates(repo_root: Path, *, files: Optional[Sequence[Path]] = None
                    ) -> Tuple[List[Tuple[str, str, int]], List[Dict[str, Any]]]:
    """Кандидаты-двери поля: (путь, имя функции, строка) + третий исход поимённо.

    Кандидат берётся по ДВУМ грубым признакам сразу: файл либо называет журнал,
    либо зовёт читателя его схемы, И внутри него есть функция одного значения,
    в теле которой стои́т настоящий разбор отметки. «Файл называет журнал» само по
    себе дверью не делает — читателя из имени не выводит никто (урок ADR-620).
    """
    found: List[Tuple[str, str, int]] = []
    unmeasured: List[Dict[str, Any]] = []
    for path in (files if files is not None else tree_files(repo_root)):
        if is_test_path(path):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unmeasured.append({"file": _rel(path, repo_root), "door": None,
                               "reason": f"файл не прочитан: {type(exc).__name__}: {exc}"})
            continue
        if JOURNAL_FILENAME not in src and not any(
                re.search(rf"\b{name}\b", src) for name in SCHEMA_READER_NAMES):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            unmeasured.append({"file": _rel(path, repo_root), "door": None,
                               "reason": f"файл не разобран: SyntaxError: {exc}"})
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            if len(args.args) != 1 or args.vararg is not None:
                continue
            if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr in _PARSE_ATTRS for n in ast.walk(node)):
                continue
            found.append((_rel(path, repo_root), node.name, node.lineno))
    return found, unmeasured


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def acceptance_of(fn: Callable[[Any], Any], forms: Dict[str, Any]) -> Dict[str, str]:
    """Вердикт двери на КАЖДОЙ объявленной форме — настоящим вызовом.

    Исключение двери есть СВОЙ исход (``raised``), а не отказ: дверь, падающая на
    форме, и дверь, вернувшая ``None``, ведут себя у вызывающего по-разному, и
    склейка спрятала бы первое за вторым.
    """
    out: Dict[str, str] = {}
    for name in FORM_NAMES:
        value = forms[name]
        try:
            out[name] = V_ACCEPT if fn(value) is not None else V_REFUSE
        except Exception as exc:  # noqa: BLE001 — исключение двери есть наблюдение
            out[name] = f"{V_RAISED}:{type(exc).__name__}"
    return out


def _accepted_set(verdicts: Dict[str, str]) -> frozenset:
    return frozenset(n for n, v in verdicts.items() if v == V_ACCEPT)


def classify_door(accepted: frozenset, guard_accepted: frozenset) -> str:
    """Класс двери относительно эталона. Перечень :data:`DOOR_CLASSES` ЗАКРЫТ."""
    if CANONICAL_FORM not in accepted:
        # Дверь, отказывающая даже канонической форме, разбирает НЕ ЭТО поле
        # (так отсеивается, например, разбор даты приказа `%Y-%m-%d`). Это
        # измеренный отсев, а не догадка по имени функции.
        return DOOR_FOREIGN
    if accepted == guard_accepted:
        return DOOR_AGREES
    if accepted > guard_accepted:
        return DOOR_WIDER
    if accepted < guard_accepted:
        return DOOR_NARROWER
    return DOOR_CROSSING


def measure_doors(repo_root: Path, *, forms: Optional[Dict[str, Any]] = None,
                  anchor: Optional[datetime] = None,
                  candidates=None, loader=None) -> Dict[str, Any]:
    """Ось A. Какие ФОРМЫ принимает каждая дверь поля — замер ИСХОДОМ.

    Форма отчёта ПОСТОЯННА: ключи объявлены всегда, «не вычислено» — ``None``.
    Эталон не загрузился ⇒ вся ось ``measured=False``: сравнивать не с чем, и
    выдавать перечень дверей без эталона значило бы выдать «не измерено» за ответ.
    """
    out: Dict[str, Any] = {
        "measured": False, "reason": None, "guard": None, "doors": [],
        "by_class": {k: 0 for k in DOOR_CLASSES}, "population": 0,
        "unmeasured": [], "forms": None,
        "form_not_execution": ("дверь зовётся настоящим вызовом; что ветка с этим "
                               "вызовом исполнялась на живой записи, прибор не "
                               "утверждает"),
    }
    forms = forms or forms_at(anchor)
    out["forms"] = {k: (v if isinstance(v, str) else repr(v)) for k, v in forms.items()}
    load = loader or (lambda path, label: _load_by_path(repo_root / path, label))

    guard_path, guard_name = GUARD_DOOR
    try:
        guard_mod = load(guard_path, "_acdc_guard")
        guard_fn = getattr(guard_mod, guard_name, None)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = (f"дверь-эталон {guard_path}::{guard_name} не загружена: "
                         f"{type(exc).__name__}: {exc}")
        return out
    if guard_fn is None:
        out["reason"] = (f"у двери-эталона {guard_path} нет имени `{guard_name}` — "
                         "сравнивать не с чем")
        return out
    guard_verdicts = acceptance_of(guard_fn, forms)
    guard_accepted = _accepted_set(guard_verdicts)
    if CANONICAL_FORM not in guard_accepted:
        out["reason"] = (f"дверь-эталон отказала канонической форме "
                         f"`{CANONICAL_FORM}` — это не дверь этого поля, и эталоном "
                         "она быть не может")
        return out
    out["guard"] = {"file": guard_path, "door": guard_name,
                    "verdicts": guard_verdicts, "accepted": sorted(guard_accepted)}

    if candidates is None:
        candidates, cand_unmeasured = door_candidates(repo_root)
    else:
        candidates, cand_unmeasured = candidates, []
    out["unmeasured"].extend(cand_unmeasured)

    for rel, name, lineno in candidates:
        try:
            module = load(rel, f"_acdc_{abs(hash((rel, name)))}")
        except Exception as exc:  # noqa: BLE001
            out["unmeasured"].append({"file": rel, "door": name,
                                      "reason": f"модуль не загружен: "
                                                f"{type(exc).__name__}: {exc}"})
            continue
        fn = getattr(module, name, None)
        if not callable(fn):
            out["unmeasured"].append({"file": rel, "door": name,
                                      "reason": "имя найдено разбором, но в модуле "
                                                "его нет или оно не вызывается"})
            continue
        verdicts = acceptance_of(fn, forms)
        accepted = _accepted_set(verdicts)
        klass = classify_door(accepted, guard_accepted)
        out["doors"].append({"file": rel, "door": name, "line": lineno,
                             "class": klass, "verdicts": verdicts,
                             "accepted": sorted(accepted),
                             "is_guard": (rel, name) == GUARD_DOOR})
    for row in out["doors"]:
        out["by_class"][row["class"]] += 1
    out["by_class"][DOOR_UNMEASURED] = len(out["unmeasured"])
    out["population"] = len(out["doors"]) + len(out["unmeasured"])
    counted = sum(out["by_class"][k] for k in DOOR_CLASSES)
    if counted != out["population"]:  # pragma: no cover — тождество учёта (инв. #17)
        out["reason"] = (f"перечень исходов не покрыл население: {counted} против "
                         f"{out['population']}")
        return out
    out["measured"] = True
    return out


# ───────────── ось B: производители ФОРМЫ записи (а не имени файла) ─────────

def _module_consts(tree: ast.Module) -> Dict[str, str]:
    """Строковые константы уровня модуля — ими бывает объявлен формат."""
    out: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _single_return_helpers(tree: ast.Module) -> Dict[str, ast.AST]:
    """Помощники ``def f(...): return <выражение>`` — шаг к форме.

    Только ОДНО возвращаемое выражение: у помощника с двумя возвратами форма
    зависит от ветки, и объявлять её одной значило бы выбрать за него.
    """
    out: Dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rets = [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Return) and n.value is not None]
            if len(rets) == 1:
                out[node.name] = rets[0]
    return out


def resolve_form(expr: ast.AST, consts: Dict[str, str], helpers: Dict[str, ast.AST],
                 *, depth: int = 0) -> Tuple[str, Optional[str], str, Optional[ast.AST]]:
    """Выражение отметки → ``(класс, род формы, подробность, узел ФОРМАТА)``.

    Классы :data:`WRITER_CLASSES` ЗАКРЫТЫ, и различие между ними существенно:
    ``relays_read_value`` НЕ ЕСТЬ писатель — он несёт ту форму, которую получил,
    и считать его писателем значило бы ответить на вопрос заказа вчетверо большим
    числом. Нераскрытое выражение есть третий исход с НАЗВАННОЙ причиной, а не
    тихо пропущенная строка.

    **Четвёртый член возврата — узел формата, который раскрытие ДЕЙСТВИТЕЛЬНО
    прошло.** Ось C спрашивает о происхождении этого формата, и искать его там
    ВТОРЫМ поиском нельзя: у производителя, раскрытого через помощника
    (``"ts": _fmt(ts)``), ``strftime`` стои́т в теле помощника, а не в узле записи, —
    второй поиск его не находил и давал «не измерено» на 25 площадках из 37 при
    нулевой связанности, то есть ПРЯТАЛ предмет оси за своей же слепотой.
    """
    if depth > RESOLVE_DEPTH:
        return (WRITER_UNMEASURED, None, f"предел раскрытия {RESOLVE_DEPTH} шагов", None)
    if isinstance(expr, ast.Constant):
        if isinstance(expr.value, str):
            return (WRITER_LITERAL, "literal", expr.value, None)
        return (WRITER_UNMEASURED, None,
                f"значение не строка: {type(expr.value).__name__}", None)
    if isinstance(expr, ast.IfExp):
        return resolve_form(expr.body, consts, helpers, depth=depth + 1)
    if isinstance(expr, ast.BoolOp) and expr.values:
        return resolve_form(expr.values[0], consts, helpers, depth=depth + 1)
    if isinstance(expr, ast.Subscript):
        return (WRITER_RELAYS, None, f"берётся чтением: {ast.unparse(expr)[:60]}", None)
    if isinstance(expr, ast.Call):
        fn = expr.func
        if isinstance(fn, ast.Attribute):
            if fn.attr == "strftime" and expr.args:
                arg = expr.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return (WRITER_PRODUCES, "strftime", arg.value, arg)
                if isinstance(arg, ast.Name) and arg.id in consts:
                    return (WRITER_PRODUCES, "strftime", consts[arg.id], arg)
                return (WRITER_UNMEASURED, None,
                        f"формат не раскрыт: {ast.unparse(arg)[:60]}", arg)
            if fn.attr == "isoformat":
                return (WRITER_PRODUCES, "iso_offset", "isoformat()", None)
            if fn.attr == "replace":
                inner = resolve_form(fn.value, consts, helpers, depth=depth + 1)
                if inner[1] == "iso_offset":
                    return (WRITER_PRODUCES, "iso_z",
                            "isoformat().replace(+00:00→Z)", None)
                return inner
            if fn.attr == "strip":
                return resolve_form(fn.value, consts, helpers, depth=depth + 1)
            if fn.attr == "time":
                return (WRITER_PRODUCES, "epoch", "time.time()", None)
            if fn.attr in _READ_ATTRS:
                return (WRITER_RELAYS, None,
                        f"берётся чтением: {ast.unparse(expr)[:60]}", None)
        if isinstance(fn, ast.Name) and fn.id in helpers:
            return resolve_form(helpers[fn.id], consts, helpers, depth=depth + 1)
        return (WRITER_UNMEASURED, None,
                f"вызов не раскрыт: {ast.unparse(expr)[:60]}", None)
    if isinstance(expr, ast.Name):
        if expr.id in consts:
            return (WRITER_LITERAL, "literal", consts[expr.id], None)
        return (WRITER_UNMEASURED, None, f"имя не раскрыто: {expr.id}", None)
    return (WRITER_UNMEASURED, None,
            f"выражение не раскрыто: {ast.unparse(expr)[:60]}", None)


def synth_form(kind: Optional[str], detail: str, forms: Dict[str, Any],
               anchor: Optional[datetime] = None) -> Optional[Any]:
    """Строка, которую производитель поставит в поле в момент-якорь.

    Это и есть мост между статической формой и ЖИВОЙ дверью: вердикт выносит не
    чтение процента-эф глазами, а сама дверь на этой строке.
    """
    a = anchor or ANCHOR
    if kind == "strftime":
        try:
            return a.strftime(detail)
        except (ValueError, TypeError):
            return None
    if kind == "iso_offset":
        return forms["isoformat_offset"]
    if kind == "iso_z":
        return forms["micros_z"]
    if kind == "epoch":
        return forms["epoch_float"]
    if kind == "literal":
        return detail
    return None


def measure_writers(repo_root: Path, *, files: Optional[Sequence[Path]] = None,
                    guard_fn: Optional[Callable[[Any], Any]] = None,
                    forms: Optional[Dict[str, Any]] = None,
                    anchor: Optional[datetime] = None,
                    loader=None) -> Dict[str, Any]:
    """Ось B. Кто производит ФОРМУ отметки этого поля — и примет ли её дверь-эталон.

    Население берётся по ФОРМЕ ЗАПИСИ (:data:`SUBJECTS`), не по имени файла и не
    по имени ключа. Вердикт выносит настоящая дверь-эталон, а не разбор формата.
    """
    out: Dict[str, Any] = {
        "measured": False, "reason": None, "population": 0,
        "by_class": {k: 0 for k in WRITER_CLASSES},
        "producers": [], "unmeasured": [],
        "production_by_door": {V_ACCEPT: 0, V_REFUSE: 0, V_UNMEASURED: 0},
        "test_by_door": {V_ACCEPT: 0, V_REFUSE: 0, V_UNMEASURED: 0},
        "subjects": {k: list(v) for k, v in SUBJECTS.items()},
        "form_not_address": ("прибор меряет ФОРМУ, а не АДРЕС: что каждый "
                             "производитель пишет именно в живое поле, не "
                             "утверждается"),
    }
    forms = forms or forms_at(anchor)
    if guard_fn is None:
        load = loader or (lambda path, label: _load_by_path(repo_root / path, label))
        guard_path, guard_name = GUARD_DOOR
        try:
            guard_fn = getattr(load(guard_path, "_acdc_guard_w"), guard_name, None)
        except Exception as exc:  # noqa: BLE001
            out["reason"] = (f"дверь-эталон не загружена: {type(exc).__name__}: {exc}")
            return out
    if not callable(guard_fn):
        out["reason"] = "дверь-эталон не вызывается — вердикт формам выносить нечем"
        return out

    for path in (files if files is not None else tree_files(repo_root)):
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError) as exc:
            out["unmeasured"].append({"file": _rel(path, repo_root), "line": None,
                                      "reason": f"{type(exc).__name__}: {exc}"})
            continue
        consts, helpers = _module_consts(tree), _single_return_helpers(tree)
        role = "test" if is_test_path(path) else "production"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            for subject, (field, companion) in SUBJECTS.items():
                if field not in keys or companion not in keys:
                    continue
                value = next(v for k, v in zip(node.keys, node.values)
                             if isinstance(k, ast.Constant) and k.value == field)
                klass, kind, detail, fmt_node = resolve_form(value, consts, helpers)
                row: Dict[str, Any] = {
                    "file": _rel(path, repo_root), "line": node.lineno,
                    "subject": subject, "role": role, "class": klass,
                    "form_kind": kind, "detail": detail[:120],
                    "stamp": None, "door": V_UNMEASURED,
                }
                # Узел формата и словари своего файла едут РЯДОМ со строкой: ось C
                # спрашивает происхождение ровно того формата, который раскрытие
                # прошло, и второго поиска у неё быть не должно.
                row[ROW_FMT_NODE] = fmt_node
                row[ROW_CONSTS] = consts
                row["_helpers_file"] = _rel(path, repo_root)
                if klass in (WRITER_PRODUCES, WRITER_LITERAL):
                    stamp = synth_form(kind, detail, forms, anchor)
                    row["stamp"] = stamp if isinstance(stamp, str) else repr(stamp)
                    if stamp is None:
                        row["door"] = V_UNMEASURED
                    else:
                        try:
                            row["door"] = (V_ACCEPT if guard_fn(stamp) is not None
                                           else V_REFUSE)
                        except Exception as exc:  # noqa: BLE001
                            row["door"] = f"{V_RAISED}:{type(exc).__name__}"
                out["producers"].append(row)

    for row in out["producers"]:
        out["by_class"][row["class"]] += 1
        if row["class"] != WRITER_PRODUCES:
            continue
        bucket = out["production_by_door"] if row["role"] == "production" \
            else out["test_by_door"]
        key = row["door"] if row["door"] in bucket else V_UNMEASURED
        bucket[key] += 1
    out["population"] = len(out["producers"])
    counted = sum(out["by_class"][k] for k in WRITER_CLASSES)
    if counted != out["population"]:  # pragma: no cover — тождество учёта (инв. #17)
        out["reason"] = (f"перечень классов не покрыл население: {counted} против "
                         f"{out['population']}")
        return out
    out["measured"] = True
    return out


# ─────────────── ось C: копии формата против СВЯЗАННОСТИ с дверью ───────────

#: Классы ПРОИСХОЖДЕНИЯ формата у производителя. Перечень ЗАКРЫТ.
FMT_OWN_LITERAL = "own_literal"
FMT_OWN_CONSTANT = "own_named_constant"
FMT_BOUND = "bound_to_door"
FMT_UNMEASURED = "unmeasured"
FMT_CLASSES: Tuple[str, ...] = (FMT_OWN_LITERAL, FMT_OWN_CONSTANT, FMT_BOUND,
                                FMT_UNMEASURED)


def door_aliases(tree: ast.Module, guard_stem: str) -> frozenset:
    """Имена, под которыми в файле доступен МОДУЛЬ двери, — только по импортам.

    Умышленно узко: ``import x.check_undelivered_work as sib`` и
    ``from x.check_undelivered_work import NAME``. Модуль, добытый в рантайме
    (``_load_by_path``), в это множество НЕ входит — и это не недосмотр, а третий
    исход: про такое происхождение прибор говорит «не измерено» с названной
    причиной. Считать «в файле упомянуто имя двери» происхождением ЗАПРЕЩЕНО —
    токен в файле читателем не делает (урок ADR-550).
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == guard_stem:
                    out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[-1] == guard_stem:
                for alias in node.names:
                    out.add(alias.asname or alias.name)
    return frozenset(out)


def format_provenance(expr: ast.AST, consts: Dict[str, str],
                      aliases: frozenset) -> Tuple[str, str]:
    """Откуда производитель взял формат → ``(класс, подробность)``.

    Различие между :data:`FMT_OWN_LITERAL`/:data:`FMT_OWN_CONSTANT` и
    :data:`FMT_BOUND` и есть предмет оси C: **РАВЕНСТВО литерала связанностью не
    является.** Названная константа в своём же файле — такая же приватная копия,
    как литерал в строке; она лишь выглядит как общее определение.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return (FMT_OWN_LITERAL, f"литерал в строке: {expr.value}")
    if isinstance(expr, ast.Name):
        if expr.id in aliases:
            return (FMT_BOUND, f"имя импортировано у двери: {expr.id}")
        if expr.id in consts:
            return (FMT_OWN_CONSTANT,
                    f"константа своего модуля: {expr.id} = {consts[expr.id]}")
        return (FMT_UNMEASURED, f"имя не раскрыто: {expr.id}")
    if isinstance(expr, ast.Attribute):
        base = expr.value
        if isinstance(base, ast.Name):
            if base.id in aliases:
                return (FMT_BOUND, f"атрибут модуля двери: {ast.unparse(expr)}")
            return (FMT_UNMEASURED,
                    f"модуль `{base.id}` не опознан как дверь по импортам — "
                    f"происхождение {ast.unparse(expr)} НЕ ИЗМЕРЕНО")
        return (FMT_UNMEASURED, f"основание атрибута не имя: {ast.unparse(expr)[:60]}")
    return (FMT_UNMEASURED, f"выражение не раскрыто: {ast.unparse(expr)[:60]}")


def measure_binding(repo_root: Path, *, doors: Dict[str, Any],
                    writers: Dict[str, Any]) -> Dict[str, Any]:
    """Ось C. Формат у производителей — СВОЯ копия или взят у двери?

    Вопрос не косметический. Согласие производителей с дверью сегодня держится ровно
    на том, что независимые копии одного литерала СЛУЧАЙНО равны: ни одна из них не
    выведена из двери, поэтому расхождение не краснит ничего и не наблюдается ничем.
    Число ``bound`` и есть ответ «сколько из них узнают о правке двери».

    Литерал, по которому сверяются копии, добывается РАЗБОРОМ файла самой двери, а
    не объявляется здесь: второй экземпляр мерки запрещён (ADR-220) — иначе прибор
    сверял бы копии со своей копией и согласие держалось бы само собой.
    """
    out: Dict[str, Any] = {
        "measured": False, "reason": None,
        "format_literal": None, "copies": 0, "bound": 0,
        "by_class": {k: 0 for k in FMT_CLASSES}, "sites": [],
        "binding_rule": ("связанной считается форма, взятая у МОДУЛЯ двери по "
                         "импорту (имя или атрибут); РАВЕНСТВО литерала "
                         "связанностью не является, названная константа своего же "
                         "файла — такая же приватная копия"),
    }
    if not doors.get("measured") or not writers.get("measured"):
        out["reason"] = ("ось C считается от осей A и B; одна из них не измерена, "
                         "и копии не от чего отсчитывать")
        return out
    guard = doors.get("guard") or {}
    guard_file, guard_door = guard.get("file"), guard.get("door")
    if not guard_file or not guard_door:
        out["reason"] = "дверь-эталон не названа осью A"
        return out
    try:
        gtree = ast.parse((repo_root / guard_file).read_text(encoding="utf-8",
                                                             errors="replace"))
    except (OSError, SyntaxError) as exc:
        out["reason"] = f"файл двери-эталона не разобран: {type(exc).__name__}: {exc}"
        return out
    literal = None
    for node in ast.walk(gtree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == guard_door:
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                        and call.func.attr == "strptime" and len(call.args) > 1 \
                        and isinstance(call.args[1], ast.Constant) \
                        and isinstance(call.args[1].value, str):
                    literal = call.args[1].value
                    break
    if literal is None:
        out["reason"] = ("формат двери-эталона не добыт разбором её файла — копии "
                         "сверять не с чем, и объявлять его здесь запрещено")
        return out
    out["format_literal"] = literal
    guard_stem = Path(guard_file).stem

    aliases_cache: Dict[str, frozenset] = {}
    for row in writers["producers"]:
        if row["class"] != WRITER_PRODUCES or row["form_kind"] != "strftime":
            continue
        if row["detail"] != literal:
            continue
        rel = row["file"]
        if rel not in aliases_cache:
            try:
                tree = ast.parse((repo_root / rel).read_text(encoding="utf-8",
                                                             errors="replace"))
                aliases_cache[rel] = door_aliases(tree, guard_stem)
            except (OSError, SyntaxError) as exc:
                out["sites"].append({"file": rel, "line": row["line"],
                                     "role": row["role"], "class": FMT_UNMEASURED,
                                     "detail": f"импорты файла не разобраны: "
                                               f"{type(exc).__name__}: {exc}"})
                continue
        node = row.get(ROW_FMT_NODE)
        if node is None:
            out["sites"].append({"file": rel, "line": row["line"],
                                 "role": row["role"], "class": FMT_UNMEASURED,
                                 "detail": ("узел формата не доехал от оси B — "
                                            "происхождение спрашивать не у чего")})
            continue
        klass, detail = format_provenance(node, row.get(ROW_CONSTS) or {},
                                          aliases_cache[rel])
        out["sites"].append({"file": rel, "line": row["line"], "role": row["role"],
                             "class": klass, "detail": detail[:140]})
    for site in out["sites"]:
        out["by_class"][site["class"]] += 1
    out["copies"] = out["by_class"][FMT_OWN_LITERAL] + out["by_class"][FMT_OWN_CONSTANT]
    out["bound"] = out["by_class"][FMT_BOUND]
    counted = sum(out["by_class"].values())
    if counted != len(out["sites"]):  # pragma: no cover — тождество учёта (инв. #17)
        out["reason"] = (f"перечень классов не покрыл площадки: {counted} против "
                         f"{len(out['sites'])}")
        return out
    out["measured"] = True
    return out


# ─────────────────────────────── сборка ─────────────────────────────────────

def strip_private_rows(writers: Optional[Dict[str, Any]]) -> None:
    """Снять служебные ключи строк оси B. Вызывается ПОСЛЕ оси C, ДО сериализации."""
    for row in (writers or {}).get("producers", []) or []:
        for key in ROW_PRIVATE:
            row.pop(key, None)


def build_report(repo_root: Path, *, now: Optional[datetime] = None,
                 anchor: Optional[datetime] = None,
                 doors=None, writers=None, binding=None) -> Dict[str, Any]:
    """Отчёт прибора. Форма ПОСТОЯННА: ключи объявлены всегда, «не вычислено» — ``None``."""
    stamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    report: Dict[str, Any] = {
        "generated_at": stamp, "order": ORDER, "measured": False,
        "status": STATUS_UNMEASURED, "reason": None, "applied": False,
        "anchor": (anchor or ANCHOR).isoformat().replace("+00:00", "Z"),
        "doors": None, "writers": None, "binding": None,
        "answer": None,
    }
    report["doors"] = doors if doors is not None else measure_doors(repo_root,
                                                                    anchor=anchor)
    report["writers"] = writers if writers is not None else measure_writers(
        repo_root, anchor=anchor)
    report["binding"] = binding if binding is not None else measure_binding(
        repo_root, doors=report["doors"], writers=report["writers"])
    # Узлы AST снимаются ПОСЛЕ оси C и ДО сериализации: артефакт обязан быть
    # записываемым, а «не записался» неотличимо от «ступень не запускалась».
    strip_private_rows(report["writers"])

    unmeasured = [name for name in ("doors", "writers", "binding")
                  if not (report[name] or {}).get("measured")]
    if unmeasured:
        reasons = "; ".join(f"{n}: {(report[n] or {}).get('reason')}"
                            for n in unmeasured)
        report["reason"] = f"не измерено {len(unmeasured)} из 3 осей — {reasons}"
        return report

    report["measured"] = True
    by_class = report["doors"]["by_class"]
    disagreeing = (by_class[DOOR_WIDER] + by_class[DOOR_NARROWER]
                   + by_class[DOOR_CROSSING])
    report["status"] = (STATUS_DOORS_DISAGREE if disagreeing
                        else STATUS_DOORS_AGREE)
    prod = report["writers"]["production_by_door"]
    report["answer"] = {
        "second_writer_exists": (prod[V_ACCEPT] + prod[V_REFUSE]) > 1,
        "production_producers": prod[V_ACCEPT] + prod[V_REFUSE] + prod[V_UNMEASURED],
        "refused_by_guard": prod[V_REFUSE],
        "doors_disagreeing": disagreeing,
        "format_copies": report["binding"]["copies"],
        "format_bound_to_door": report["binding"]["bound"],
    }
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append("двери часов поля журнала (заказ G110 п. 3): НЕ ИЗМЕРЕНО — "
                     f"{report.get('reason')}")
        return lines
    doors, writers, binding = report["doors"], report["writers"], report["binding"]
    answer = report["answer"]
    lines.append(f"двери часов поля журнала (заказ G110 п. 3): {report['status']}")
    guard = doors["guard"]
    lines.append(f"[ОСЬ A] эталон {guard['file']}::{guard['door']} принимает "
                 f"{len(guard['accepted'])} из {len(FORM_NAMES)} форм: "
                 f"{', '.join(guard['accepted'])}")
    lines.append("[ОСЬ A] дверей " + str(doors["population"]) + "; "
                 + " · ".join(f"{k} {v}" for k, v in doors["by_class"].items() if v))
    for row in doors["doors"]:
        if row["class"] in (DOOR_AGREES, DOOR_FOREIGN):
            continue
        extra = sorted(set(row["accepted"]) - set(guard["accepted"]))
        lines.append(f"[ОСЬ A] {row['class']}: {row['file']}::{row['door']} — "
                     f"принимает СВЕРХ эталона {', '.join(extra) or '—'}")
    for row in doors["unmeasured"]:
        lines.append(f"[ОСЬ A] НЕ ИЗМЕРЕНО: {row['file']}"
                     f"{'::' + row['door'] if row.get('door') else ''} — {row['reason']}")
    lines.append(f"[ОСЬ B] производителей формы в production "
                 f"{answer['production_producers']} "
                 f"(дверь принимает {writers['production_by_door'][V_ACCEPT]} · "
                 f"отказывает {writers['production_by_door'][V_REFUSE]}); "
                 f"население {writers['population']}, "
                 + " · ".join(f"{k} {v}" for k, v in writers["by_class"].items() if v))
    for row in writers["producers"]:
        if row["class"] == WRITER_PRODUCES and row["role"] == "production":
            lines.append(f"[ОСЬ B] {row['file']}:{row['line']} [{row['subject']}] "
                         f"{row['form_kind']}={row['detail']} → {row['stamp']} ⇒ "
                         f"дверь {row['door']}")
    lines.append(f"[ОСЬ C] литерал двери `{binding['format_literal']}`: площадок "
                 f"{len(binding['sites'])} — приватных копий {binding['copies']} "
                 f"(" + " · ".join(f"{k} {v}" for k, v in binding["by_class"].items()
                                   if v) + f"), СВЯЗАНО с дверью {binding['bound']}; "
                 "равенство литералов связанностью не является")
    if answer["second_writer_exists"]:
        lines.append("ОТВЕТ ЗАКАЗА: писатель НЕ ОДИН — производителей формы "
                     f"{answer['production_producers']}, и посылка «единственный "
                     "писатель пишет секунды» измеренно неверна")
    if report["status"] == STATUS_DOORS_DISAGREE:
        lines.append(f"ВЫВОД: у одного поля {answer['doors_disagreeing']} "
                     "двер(и/ей) ШИРЕ или УЖЕ той, что гейтит взятие карточки — один "
                     "и тот же текст у одного читателя датирован, у другого «метка не "
                     "разобрана»; расхождение не краснит ничего")
    lines.append("НЕ ДОКЛАДЫВАЕТ: пишет ли производитель формы именно в ЖИВОЕ поле "
                 "(форма, а не адрес) · исполняется ли ветка с вызовом двери · какой "
                 "дверь ДОЛЖНА быть (это замер расхождения, а не предложение порога)")
    lines.append("ADVISORY: прибор только ЧИТАЕТ (applied=False) — ни одна строка "
                 "сторожа, RiskPolicy v1.0, стоп-крана, аллокатора, живого трека и "
                 "landing/ не трогается; дверь НЕ расширяется (заказ это запретил)")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до шага 0-офис, иначе отсутствие файла неотличимо от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root, now=now)
    try:
        save_artifact(report, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def exit_code_for(report: Dict[str, Any]) -> int:
    if not report.get("measured"):
        return 2
    return 0 if report["status"] == STATUS_DOORS_AGREE else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root \
        else Path(__file__).resolve().parents[2]
    report = build_report(repo_root)
    if args.save:
        save_artifact(report, repo_root / "data")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    return exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
