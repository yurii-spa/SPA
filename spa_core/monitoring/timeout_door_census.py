#!/usr/bin/env python3
"""Какая ДВЕРЬ пускает случай пережить `--timeout` — замер у ВЫЗОВА (заказ G108 п. 2).

**Зачем (цикл #814, 2026-10-09; заказ поставлен ADR-534 01.10, лежал остатком восемь
суток).** ADR-534 нашёл в записи прогона случай, который прожил **407,1 с при
`--timeout=180`** и закончился `ok`: порог его НЕ ВЗЯЛ. Заказ запретил спрашивать
«поднять ли порог» и поставил другой вопрос:

> «Спросить надо не «поднять ли порог», а **какая дверь блокируется в C-коде** у этого
> населения — и мерить у вызова, а не по имени теста. Три исхода обязательны.»

**Посылка заказа — ГИПОТЕЗА, и прибор её меряет, а не повторяет.** Фраза «SIGALRM не
прерывает блокировку в C-коде» живёт в репозитории как ПРОЗА: `ci_verdict.py`,
`pytest_stream_record.py`, `step_time_census.py` и сам ADR-474 повторяют её друг за
другом, и ни одно из четырёх мест не несёт числа. Поэтому батарея ниже
(`live_door_verdicts`) гонит дочерний pytest с ТЕМИ ЖЕ флагами и спрашивает у каждой
двери отдельно: взял её порог или нет. Утверждения тут нет ни одного — есть замер.

## Три оси, и ни одна не заменяет другую

| ось | вопрос | чего НЕ знает |
|---|---|---|
| `population_from_stream` | какие случаи пережили порог? | ПОЧЕМУ пережили |
| `door_sites` | где в дереве стои́т вызов, гасящий срок? | исполняется ли он |
| `live_door_verdicts` | гасит ли класс двери срок НА САМОМ ДЕЛЕ? | есть ли он в нашем дереве |

Статическая ось даёт ВЕРХНИЙ край (место есть — исполнение не измерено; урок ADR-674:
дорога есть достижимость, а не исполнение), живой сторож `watch_doors` — НИЖНИЙ
(проход был, и у него есть кадр вызова). Склеивать их в одно число запрещено.

## Почему «у вызова», а не «по имени теста»

Имя теста отвечает на вопрос «кто долго жил». Дверь — это ВЫЗОВ: `signal.alarm(0)`
в `finally` чужого помощника гасит `ITIMER_REAL`, поставленный pytest-timeout на ВЕСЬ
случай, и после этого срока у случая нет вовсе — ни в этой фазе, ни в следующей.
Поэтому и статическая ось, и живой сторож называют `файл:строка` + текст самого
вызова, а не тест, внутри которого он случился.

## Закрытый перечень классов двери

* `alarm_cancelled` — `signal.alarm(0)` / `setitimer(ITIMER_REAL, 0)`: срок СНЯТ;
* `alarm_replaced` — то же с ненулевым аргументом: срок ЗАМЕНЁН на свой;
* `handler_replaced` — `signal.signal(SIGALRM, …)`: обработчик подменён (в том числе
  на `SIG_IGN`, и тогда сигнал не делает ничего вообще);
* `verdict_swallowed` — `except BaseException` / `except:` без `raise`: срок сработал,
  исключение проглочено, и случай доложился **зелёным**. Эта дверь стены почти не
  удлиняет — то есть признак «вдвое дольше порога» её не видит ПО ПОСТРОЕНИЮ;
* `alarm_arg_unparsed` — вызов `alarm`/`setitimer` есть, аргумент не литерал ⇒ **третий
  исход** с названной причиной, а не отнесение к одному из классов по догадке.

Прибор только ЧИТАЕТ дерево и ГОНИТ свою батарею в одноразовом каталоге: ни теста, ни
порога, ни воркфлоу, ни базы храповика он не трогает. Коды возврата: **0** — измерено
(в том числе измерено и равно нулю) · **1** — находка названа · **2** — НЕ ИЗМЕРЕНО с
названной причиной. Только stdlib (инв. #4); LLM здесь нет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "timeout_door_census/v1"

# ── классы двери: закрытый перечень (читается тестами) ────────────────────────
DOOR_ALARM_CANCELLED = "alarm_cancelled"
DOOR_ALARM_REPLACED = "alarm_replaced"
DOOR_HANDLER_REPLACED = "handler_replaced"
DOOR_VERDICT_SWALLOWED = "verdict_swallowed"
DOOR_ARG_UNPARSED = "alarm_arg_unparsed"
DOOR_CLASSES: Tuple[str, ...] = (
    DOOR_ALARM_CANCELLED,
    DOOR_ALARM_REPLACED,
    DOOR_HANDLER_REPLACED,
    DOOR_VERDICT_SWALLOWED,
    DOOR_ARG_UNPARSED,
)

# ── исходы случая против порога: закрытый перечень ────────────────────────────
CASE_TAKEN = "taken"
CASE_SURVIVED = "survived_ok"
CASE_UNTERMINATED = "unterminated"
CASE_OUTCOMES: Tuple[str, ...] = (CASE_TAKEN, CASE_SURVIVED, CASE_UNTERMINATED)

# ── вердикт живой двери: закрытый перечень ────────────────────────────────────
LIVE_DEFEATED = "defeated"
LIVE_TAKEN = "taken"
#: Вердикт срока ВЫНЕСЕН вовремя, а случай всё равно прожил дольше порога: его
#: РАЗБОРКА не кончается (например `ThreadPoolExecutor.__exit__` ждёт работников).
#: Это НЕ дверь: порог сработал. Но и не «уложился»: стена больше порога, и в
#: записи прогона такой случай выглядит ровно как переживший его.
LIVE_TAKEN_LATE = "taken_late"
LIVE_UNMEASURED = "unmeasured"
LIVE_VERDICTS: Tuple[str, ...] = (LIVE_DEFEATED, LIVE_TAKEN, LIVE_TAKEN_LATE,
                                  LIVE_UNMEASURED)

#: Имена, которыми зовут часовой механизм процесса.
_TIMER_CALLS = {"alarm", "setitimer"}

#: Отказ ЧУЖОГО кода, который обходчик населения вправе проглотить и пойти
#: дальше. Всё остальное из `BaseException` — не отказ обойдённого модуля, а СРОК
#: прогона (`Failed` pytest-timeout) либо прерывание оператора
#: (`KeyboardInterrupt`), и проглотить это значит остаться без срока до конца
#: случая: таймер `ITIMER_REAL` одноразовый, второго срабатывания не будет.
#:
#: `SystemExit` здесь ЧУЖОЙ намеренно: модуль с CLI вправе позвать `sys.exit()`
#: из своей точки входа, и обходчик обязан это пережить.
FOREIGN_FAILURE: Tuple[type, ...] = (Exception, SystemExit)


def is_foreign_failure(exc: BaseException) -> bool:
    """Это отказ обойдённого модуля, а не срок прогона?

    Правило живёт ОДНОЙ копией: обходчиков в дереве несколько, и второй экземпляр
    правила разошёлся бы с первым молча.
    """
    return isinstance(exc, FOREIGN_FAILURE)


WHAT_IT_DOES_NOT_PROVE = (
    "что найденное место ИСПОЛНЯЕТСЯ: статическая ось — верхний край, и дорога есть "
    "достижимость, а не исполнение (ADR-674)",
    "что перечень классов двери полон: он ВХОД прибора, и цена его состава видна по "
    "числу `alarm_arg_unparsed` и по вердиктам контролей батареи",
    "что случай с исходом `ok` и стеной ниже порога срок не пересекал: проглоченный "
    "вердикт стены не удлиняет, и запись о нём молчит по построению",
    "что КАЖДЫЙ случай со стеной больше порога прошёл дверь: вердикт срока бывает "
    "вынесен вовремя, а разборка случая не кончается (`taken_late`) — тогда стена "
    "больше порога, а двери не было",
)


# ══════════════════════════════════════════════════════════════════════════════
# ОСЬ 1 — население: какие случаи пережили порог (читается у записи прогона)
# ══════════════════════════════════════════════════════════════════════════════
def read_threshold(args: Sequence[str]) -> Tuple[Optional[float], Optional[str], str]:
    """Порог и метод — У САМОЙ ЗАПИСИ, а не перепечаткой из текста воркфлоу.

    Возвращает ``(порог, метод, причина)``. Порог не объявлен ⇒ ``(None, …, причина)``:
    сравнивать стену не с чем, и «провалов не найдено» тут не утверждается.
    """
    threshold: Optional[float] = None
    method: Optional[str] = None
    for item in args:
        text = str(item)
        if text.startswith("--timeout="):
            raw = text.split("=", 1)[1]
            try:
                threshold = float(raw)
            except ValueError:
                return None, method, f"порог не разобран: `{text}`"
        elif text.startswith("--timeout-method="):
            method = text.split("=", 1)[1]
    if threshold is None:
        return None, method, "в командной строке записи нет `--timeout=`"
    return threshold, method, ""


def population_from_stream(path: Path) -> dict:
    """Случаи, прожившие НЕ МЕНЬШЕ порога, разложенные по закрытому перечню исходов.

    ``unterminated`` — это `start` без исхода: случай не вернулся вовсе, и стена у него
    не «большая», а НЕ ОГРАНИЧЕННАЯ сверху. Ноль таких случаев и отсутствие записи —
    разные ответы, и печатаются они разными словами.
    """
    doc: dict = {"schema": VERSION, "source": str(path), "measured": False,
                 "threshold_s": None, "method": None,
                 "counts": {k: 0 for k in CASE_OUTCOMES}, "cases": [],
                 "cases_total": 0, "reason": ""}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        doc["reason"] = f"запись не прочитана: {type(exc).__name__}: {exc}"
        return doc

    session: Optional[dict] = None
    starts: Dict[str, float] = {}
    closed: List[Tuple[str, float, str]] = []
    bad_lines = 0
    extra_outcomes = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad_lines += 1
            continue
        if not isinstance(row, dict):
            bad_lines += 1
            continue
        kind = row.get("e")
        if kind == "session":
            session = row
            continue
        name, moment = row.get("n"), row.get("t")
        if not isinstance(name, str) or not isinstance(moment, (int, float)):
            bad_lines += 1
            continue
        if kind == "start":
            starts[name] = float(moment)
        else:
            began = starts.pop(name, None)
            if began is None:
                # Исход БЕЗ открытого `start` — это не мусор: `subTest` печатает
                # несколько исходов на один случай, и записывать их в «строка не
                # разобрана» значило бы спрятать известный класс под третьим
                # исходом. Два счётчика, а не один.
                extra_outcomes += 1
                continue
            closed.append((name, float(moment) - began, str(kind)))
    doc["unparsed_lines"] = bad_lines
    doc["extra_outcome_lines"] = extra_outcomes

    if session is None:
        doc["reason"] = "в записи нет строки `session` — порог не объявлен ничем"
        return doc
    threshold, method, why = read_threshold(session.get("args") or [])
    doc["method"] = method
    if threshold is None:
        doc["reason"] = why
        return doc

    doc.update(measured=True, threshold_s=threshold)
    rows: List[dict] = []
    for name, wall, kind in closed:
        if wall < threshold:
            continue
        outcome = CASE_SURVIVED if kind == "ok" else CASE_TAKEN
        rows.append({"case": name, "wall_s": round(wall, 3), "record_outcome": kind,
                     "outcome": outcome})
    # `start` без исхода остался в `starts`: случай не вернулся. Стена у него не
    # меряется ВОВСЕ — записать её числом значило бы выдать обрыв за длительность.
    for name in sorted(starts):
        rows.append({"case": name, "wall_s": None, "record_outcome": None,
                     "outcome": CASE_UNTERMINATED})
    counts = Counter(r["outcome"] for r in rows)
    doc["counts"] = {k: counts.get(k, 0) for k in CASE_OUTCOMES}
    doc["cases"] = sorted(rows, key=lambda r: (r["outcome"], -(r["wall_s"] or 0.0)))
    doc["cases_total"] = len(rows)
    doc["cases_closed"] = len(closed)
    return doc


# ══════════════════════════════════════════════════════════════════════════════
# ОСЬ 2 — места двери: где стои́т вызов, гасящий срок (статически, У ВЫЗОВА)
# ══════════════════════════════════════════════════════════════════════════════
def _attr_name(node: ast.AST) -> str:
    """Имя вызываемого так, как оно НАПИСАНО: `signal.alarm` / `alarm`."""
    if isinstance(node, ast.Attribute):
        return f"{_attr_name(node.value)}.{node.attr}" if node.value is not None else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _mentions_sigalrm(node: ast.AST) -> bool:
    """Аргумент называет SIGALRM/ITIMER_REAL? Спрашивается у ДЕРЕВА, не подстрокой."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in ("SIGALRM", "ITIMER_REAL"):
            return True
        if isinstance(sub, ast.Name) and sub.id in ("SIGALRM", "ITIMER_REAL"):
            return True
    return False


def _literal_zero(node: ast.AST) -> Optional[bool]:
    """Литеральный ноль? ``None`` — аргумент не литерал (третий исход у вызова)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value) == 0.0
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_zero(node.operand)
        return inner
    return None


def _handler_reraises(handler: ast.ExceptHandler) -> bool:
    """Обработчик возвращает исключение наружу? `raise` ИЛИ `raise X` — оба считаются.

    Вложенные `try` внутри обработчика не разбираются: `raise` где угодно в его теле
    считается возвратом. Односторонность НАЗВАНА и смещена в сторону МОЛЧАНИЯ —
    прибор скорее не назовёт дверь, чем выдумает её.
    """
    return any(isinstance(sub, ast.Raise) for sub in ast.walk(handler))


def _catches_base_exception(handler: ast.ExceptHandler) -> bool:
    """`except:` или `except BaseException` — то есть ловит и исход pytest-timeout.

    `Failed` pytest-timeout наследует `BaseException`, а не `Exception`: обычный
    `except Exception` его НЕ ловит, и дверью не является.
    """
    if handler.type is None:
        return True
    kinds = ([handler.type] if not isinstance(handler.type, ast.Tuple)
             else list(handler.type.elts))
    return any(_attr_name(k).split(".")[-1] == "BaseException" for k in kinds)


def door_sites_in_source(text: str, *, where: str) -> Tuple[List[dict], str]:
    """Места двери в ОДНОМ исходнике. Разобрать не вышло ⇒ названная причина."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    out: List[dict] = []

    def _site(node: ast.AST, door: str, note: str = "") -> dict:
        # `ast.get_source_segment` сам считается с тем, что `col_offset` — БАЙТЫ
        # (урок ADR-650): резать исходник руками по позициям узла на кириллице
        # отрезало бы не там.
        call_text = ast.get_source_segment(text, node) or ""
        return {"file": where, "line": getattr(node, "lineno", 0), "door": door,
                "call": " ".join(call_text.split())[:200], "note": note}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _attr_name(node.func)
            tail = name.split(".")[-1]
            if tail in _TIMER_CALLS and node.args:
                arg = node.args[-1] if tail == "setitimer" else node.args[0]
                if tail == "setitimer" and not _mentions_sigalrm(node.args[0]):
                    continue           # ITIMER_VIRTUAL/PROF срок pytest-timeout не несут
                zero = _literal_zero(arg)
                if zero is None:
                    out.append(_site(node, DOOR_ARG_UNPARSED,
                                     "аргумент не литерал — класс не назначен"))
                else:
                    out.append(_site(node, DOOR_ALARM_CANCELLED if zero
                                     else DOOR_ALARM_REPLACED))
            elif tail == "signal" and len(node.args) >= 1 and _mentions_sigalrm(node.args[0]):
                out.append(_site(node, DOOR_HANDLER_REPLACED))
        elif isinstance(node, ast.ExceptHandler):
            if _catches_base_exception(node) and not _handler_reraises(node):
                out.append(_site(node, DOOR_VERDICT_SWALLOWED))
    return out, ""


def door_sites(tree_root: Path, *, subdirs: Sequence[str] = ("spa_core", "scripts")
               ) -> dict:
    """Перепись мест двери по дереву. Нет файлов ⇒ НЕ ИЗМЕРЕНО, а не «чисто»."""
    tree_root = Path(tree_root)
    doc: dict = {"schema": VERSION, "tree_root": str(tree_root), "measured": False,
                 "sites": [], "counts": {k: 0 for k in DOOR_CLASSES},
                 "files_scanned": 0, "files_unparsed": [], "reason": ""}
    files: List[Path] = []
    for sub in subdirs:
        base = tree_root / sub
        if base.is_dir():
            files.extend(sorted(base.rglob("*.py")))
    if not files:
        doc["reason"] = (f"ни одного файла `*.py` в {list(subdirs)} под {tree_root} — "
                         "перепись не над чем гнать")
        return doc
    # Исключения для СЕБЯ здесь нет намеренно. Прибор живёт в населении, которое
    # мерит (урок ADR-620), и молчаливый пропуск своего файла был бы ровно тем
    # вырожденным заслоном, который снимается незаметно: сегодня в нём ни одной
    # двери, и это ЗАМЕР (сторож `the_instrument_does_not_become_its_own_finding`),
    # а не договорённость. Появится дверь — тест покраснеет, и решение о ней
    # будет принято вслух.
    sites: List[dict] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            doc["files_unparsed"].append({"file": str(path), "reason": str(exc)})
            continue
        try:
            rel = str(path.relative_to(tree_root))
        except ValueError:             # pragma: no cover - путь вне дерева
            rel = str(path)
        found, why = door_sites_in_source(text, where=rel)
        if why:
            doc["files_unparsed"].append({"file": rel, "reason": why})
            continue
        doc["files_scanned"] += 1
        sites.extend(found)
    counts = Counter(s["door"] for s in sites)
    doc.update(measured=True, sites=sites,
               counts={k: counts.get(k, 0) for k in DOOR_CLASSES},
               sites_total=len(sites))
    return doc


# ══════════════════════════════════════════════════════════════════════════════
# ОСЬ 3 — живая батарея: гасит ли класс двери срок НА САМОМ ДЕЛЕ
# ══════════════════════════════════════════════════════════════════════════════
#: Сцена батареи. Ключ — имя случая, значение — тело. Половина населения —
#: КОНТРОЛИ: двери, которые обязаны быть ВЗЯТЫ порогом. Контроль, оказавшийся
#: `defeated`, и есть подтверждение посылки заказа про блокировку в C-коде.
BATTERY: Tuple[Tuple[str, str, str], ...] = (
    (DOOR_ALARM_CANCELLED, "door_alarm_cancelled",
     "signal.alarm(0)\n    time.sleep(OVER)"),
    (DOOR_ALARM_CANCELLED, "door_itimer_cancelled",
     "signal.setitimer(signal.ITIMER_REAL, 0)\n    time.sleep(OVER)"),
    (DOOR_ALARM_REPLACED, "door_alarm_replaced",
     "signal.alarm(int(OVER) + 60)\n    time.sleep(OVER)"),
    (DOOR_HANDLER_REPLACED, "door_handler_ignored",
     "signal.signal(signal.SIGALRM, signal.SIG_IGN)\n    time.sleep(OVER)"),
    (DOOR_VERDICT_SWALLOWED, "door_verdict_swallowed",
     "try:\n        time.sleep(OVER)\n    except BaseException:\n        pass"),
    ("control_c_block_sleep", "control_plain_sleep", "time.sleep(OVER)"),
    ("control_c_block_waitpid", "control_subprocess_wait",
     "subprocess.run([sys.executable, '-c', 'import time; time.sleep(%s)' % OVER])"),
    ("control_c_block_lock", "control_lock_held",
     "lock = threading.Lock()\n    lock.acquire()\n    lock.acquire()"),
    ("control_c_block_regex", "control_regex_backtracking",
     "re.match(r'(a+)+$', 'a' * 32 + 'b')"),
    ("control_c_block_event", "control_event_wait", "threading.Event().wait()"),
    ("control_c_block_condition", "control_condition_wait",
     "cv = threading.Condition()\n    with cv:\n        cv.wait()"),
    ("control_c_block_join", "control_thread_join",
     "t = threading.Thread(target=time.sleep, args=(OVER,))\n    t.start()\n    t.join()"),
    ("control_teardown_waits", "control_thread_pool_map",
     "with ThreadPoolExecutor(max_workers=2) as pool:\n"
     "        for _ in pool.map(time.sleep, [OVER, OVER]):\n            pass"),
)

_BATTERY_HEAD = ("import re, signal, subprocess, sys, threading, time\n"
                 "from concurrent.futures import ThreadPoolExecutor\n\n"
                 "OVER = {over!r}\n\n")


def battery_source(*, over_s: float, cases: Sequence[Tuple[str, str, str]] = BATTERY
                   ) -> str:
    """Исходник сцены батареи. Сцена — ВХОД, и её текст виден целиком."""
    parts = [_BATTERY_HEAD.format(over=over_s)]
    for _door, name, body in cases:
        parts.append(f"def test_{name}():\n    {body}\n\n")
    return "".join(parts)


def _junit_outcomes(path: Path) -> Tuple[Dict[str, Tuple[str, float]], str]:
    """Исход и длительность каждого случая дочернего прогона — у его junit-записи."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return {}, f"junit не прочитан: {type(exc).__name__}: {exc}"
    out: Dict[str, Tuple[str, float]] = {}
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        kind = "ok"
        for child in case:
            if child.tag in ("failure", "error"):
                kind = child.tag
            elif child.tag == "skipped":
                kind = "skipped"
        try:
            seconds = float(case.get("time") or 0.0)
        except ValueError:             # pragma: no cover - чужой писатель
            seconds = 0.0
        out[name] = (kind, seconds)
    if not out:
        return {}, "в junit-записи дочернего прогона нет ни одного случая"
    return out, ""


def live_door_verdicts(*, deadline_s: float = 2.0, over_s: float = 6.0,
                       python: Optional[str] = None,
                       workdir: Optional[Path] = None,
                       cases: Sequence[Tuple[str, str, str]] = BATTERY,
                       run: Optional[Callable[[Sequence[str], Path], int]] = None
                       ) -> dict:
    """Гонит батарею дочерним pytest с ТЕМИ ЖЕ флагами и судит каждую дверь.

    Вердикт у двери один из трёх: `defeated` — случай прожил не меньше срока и
    доложился зелёным · `taken` — порог его снял · `unmeasured` — случая нет в записи
    дочернего прогона либо записи нет вовсе. Нуля и скипа тут не бывает: скип — это
    `unmeasured` с названной причиной, а не «прошло» (урок `pyflakes`).
    """
    doc: dict = {"schema": VERSION, "measured": False, "deadline_s": deadline_s,
                 "over_s": over_s, "verdicts": {}, "rows": [], "reason": ""}
    holder = None
    if workdir is None:
        holder = tempfile.TemporaryDirectory(prefix="spa_timeout_doors_")
        workdir = Path(holder.name)
    workdir = Path(workdir)
    try:
        scene = workdir / "test_timeout_doors_battery.py"
        scene.write_text(battery_source(over_s=over_s, cases=cases), encoding="utf-8")
        junit = workdir / "junit-battery.xml"
        argv = [python or sys.executable, "-m", "pytest", scene.name,
                "-p", "no:randomly", "-q", "--timeout=%s" % deadline_s,
                "--timeout-method=signal", "--junitxml=%s" % junit.name]
        if run is not None:
            rc = run(argv, workdir)
        else:
            try:
                rc = subprocess.run(argv, cwd=str(workdir), capture_output=True,
                                    text=True, timeout=max(120.0, over_s * len(cases) * 3)
                                    ).returncode
            except (OSError, subprocess.SubprocessError) as exc:
                doc["reason"] = f"батарея не прогнана: {type(exc).__name__}: {exc}"
                return doc
        doc["child_rc"] = rc
        outcomes, why = _junit_outcomes(junit)
        if why:
            doc["reason"] = why
            return doc
        rows: List[dict] = []
        for door, name, _body in cases:
            key = f"test_{name}"
            seen = outcomes.get(key)
            if seen is None:
                rows.append({"door": door, "case": key, "verdict": LIVE_UNMEASURED,
                             "reason": "случая нет в junit-записи дочернего прогона"})
                continue
            kind, seconds = seen
            if kind == "skipped":
                rows.append({"door": door, "case": key, "verdict": LIVE_UNMEASURED,
                             "wall_s": seconds, "reason": "случай пропущен"})
            elif kind == "ok" and seconds >= deadline_s:
                rows.append({"door": door, "case": key, "verdict": LIVE_DEFEATED,
                             "wall_s": seconds})
            elif kind == "ok":
                rows.append({"door": door, "case": key, "verdict": LIVE_UNMEASURED,
                             "wall_s": seconds,
                             "reason": ("случай уложился в срок — сцена не дошла до "
                                        "двери, и о двери он не говорит ничего")})
            elif seconds >= deadline_s * 2:
                # Порог СРАБОТАЛ (исход — провал), но случай всё равно прожил
                # вдвое дольше: его разборка не кончается. Слить это с `taken`
                # значило бы потерять единственную форму, при которой «стена
                # больше порога» НЕ означает двери.
                rows.append({"door": door, "case": key,
                             "verdict": LIVE_TAKEN_LATE, "wall_s": seconds})
            else:
                rows.append({"door": door, "case": key, "verdict": LIVE_TAKEN,
                             "wall_s": seconds})
        doc["rows"] = rows
        doc["verdicts"] = {r["case"]: r["verdict"] for r in rows}
        doc["counts"] = {k: sum(1 for r in rows if r["verdict"] == k)
                         for k in LIVE_VERDICTS}
        doc["measured"] = True
        return doc
    finally:
        if holder is not None:
            holder.cleanup()


# ══════════════════════════════════════════════════════════════════════════════
# ОСЬ 4 — живой сторож: проход через дверь, названный КАДРОМ ВЫЗОВА
# ══════════════════════════════════════════════════════════════════════════════
class DoorWatch:
    """Записывает КАЖДЫЙ проход через часовой механизм процесса — у вызова.

    Поведение не меняется ни в чём: обёртка зовёт настоящую функцию. Меняется
    только то, что проход перестаёт быть невидимым. Кадр берётся у ВЫЗЫВАЮЩЕГО
    (`sys._getframe(1)`), поэтому в записи стои́т `файл:строка` того места, где
    срок погасили, а не имя теста, внутри которого это случилось.
    """

    def __init__(self, journal: Optional[Path] = None) -> None:
        self.passages: List[dict] = []
        self._saved: Dict[str, Callable] = {}
        # Проход дописывается СРАЗУ, если дан журнал. Ответ, записанный один раз в
        # конце, теряется целиком у прогона, который не кончается — а именно такие
        # прогоны этот сторож и мерит (тот же урок, что у `_artifact_stamp_clock_probe`:
        # «ответ пишется ПОСЛЕ КАЖДОГО модуля»). Без журнала поведение прежнее.
        self.journal = Path(journal) if journal is not None else None

    def _record(self, name: str, args: tuple) -> None:
        frame = sys._getframe(2)
        door = DOOR_HANDLER_REPLACED
        if name in _TIMER_CALLS:
            value = args[-1] if (name == "setitimer" and len(args) > 1) else (
                args[0] if args else None)
            if isinstance(value, (int, float)):
                door = (DOOR_ALARM_CANCELLED if float(value) == 0.0
                        else DOOR_ALARM_REPLACED)
            else:
                door = DOOR_ARG_UNPARSED
        row = {"call": f"signal.{name}", "door": door,
               "file": frame.f_code.co_filename,
               "line": frame.f_lineno,
               "function": frame.f_code.co_name,
               "args": [repr(a)[:80] for a in args]}
        self.passages.append(row)
        if self.journal is not None:
            with self.journal.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()

    def install(self) -> "DoorWatch":
        for name in ("alarm", "setitimer", "signal"):
            original = getattr(signal, name)
            self._saved[name] = original

            def wrapper(*args, _name=name, _original=original, **kwargs):
                self._record(_name, args)
                return _original(*args, **kwargs)

            setattr(signal, name, wrapper)
        return self

    def remove(self) -> None:
        for name, original in self._saved.items():
            setattr(signal, name, original)
        self._saved.clear()

    def __enter__(self) -> "DoorWatch":
        return self.install()

    def __exit__(self, *exc) -> bool:
        self.remove()
        return False

    def report(self) -> dict:
        counts = Counter(p["door"] for p in self.passages)
        return {"schema": VERSION, "measured": True,
                "passages": self.passages, "passages_total": len(self.passages),
                "counts": {k: counts.get(k, 0) for k in DOOR_CLASSES}}


def watch_doors(journal: Optional[Path] = None) -> DoorWatch:
    """Сторож проходов через дверь. Нижний край: проход был и у него есть кадр.

    ``journal`` — путь `.jsonl`, куда проход дописывается СРАЗУ. Нужен ровно там,
    где сторож полезнее всего: у прогона, который не кончается, сводки в конце не
    будет никогда.
    """
    return DoorWatch(journal=journal)


def passages_from_journal(path: Path) -> dict:
    """Прочитать дописанный журнал проходов. Нет файла ⇒ НЕ ИЗМЕРЕНО с причиной."""
    doc: dict = {"schema": VERSION, "measured": False, "passages": [],
                 "passages_total": 0, "counts": {k: 0 for k in DOOR_CLASSES},
                 "unparsed_lines": 0, "reason": ""}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        doc["reason"] = f"журнал проходов не прочитан: {type(exc).__name__}: {exc}"
        return doc
    rows: List[dict] = []
    bad = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict) and row.get("door") in DOOR_CLASSES:
            rows.append(row)
        else:
            bad += 1
    counts = Counter(r["door"] for r in rows)
    doc.update(measured=True, passages=rows, passages_total=len(rows),
               counts={k: counts.get(k, 0) for k in DOOR_CLASSES},
               unparsed_lines=bad)
    return doc


# ── pytest-плагин: `-p spa_core.monitoring.timeout_door_census` ───────────────
_WATCH: Optional[DoorWatch] = None
WATCH_OUT_ENV = "SPA_TIMEOUT_DOOR_WATCH"


def pytest_configure(config) -> None:                  # pragma: no cover - плагин
    """Ставит сторожа на весь прогон. Файла ответа нет ⇒ плагин НЕ включается."""
    import os
    global _WATCH
    out = os.environ.get(WATCH_OUT_ENV)
    if not out:
        return
    # `.jsonl` ⇒ дописывать СРАЗУ: прогон, который не кончается, сводки не оставит.
    _WATCH = watch_doors(journal=Path(out) if out.endswith(".jsonl") else None).install()


def pytest_sessionfinish(session, exitstatus) -> None:  # pragma: no cover - плагин
    import os
    global _WATCH
    if _WATCH is None:
        return
    out = os.environ.get(WATCH_OUT_ENV)
    report = _WATCH.report()
    _WATCH.remove()
    _WATCH = None
    if out and not out.endswith(".jsonl"):
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                             encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Печать и точка входа
# ══════════════════════════════════════════════════════════════════════════════
RC_MEASURED = 0
RC_FINDING = 1
RC_UNMEASURED = 2


def format_population(doc: dict) -> str:
    if not doc.get("measured"):
        return ("   порог пережили: НЕ ИЗМЕРЕНО — " + (doc.get("reason") or "причина не названа"))
    counts = doc["counts"]
    head = (f"   порог {doc['threshold_s']:g} с (метод {doc.get('method') or 'не объявлен'}) · "
            f"случаев в записи {doc.get('cases_closed', 0)} "
            f"(+{doc.get('extra_outcome_lines', 0)} исходов subTest, "
            f"{doc.get('unparsed_lines', 0)} строк не разобрано) · "
            f"на пороге и выше {doc['cases_total']}: "
            f"снял порог {counts[CASE_TAKEN]} · ПЕРЕЖИЛИ {counts[CASE_SURVIVED]} · "
            f"не вернулись {counts[CASE_UNTERMINATED]}")
    lines = [head]
    for row in doc["cases"]:
        if row["outcome"] == CASE_TAKEN:
            continue
        wall = "не ограничена" if row["wall_s"] is None else f"{row['wall_s']:.1f} с"
        lines.append(f"     [{row['outcome']}] {wall} — {row['case']}")
    if counts[CASE_SURVIVED] == 0 and counts[CASE_UNTERMINATED] == 0:
        lines.append("     измерено и равно нулю: порог снял КАЖДЫЙ случай, "
                     "который его достиг")
    return "\n".join(lines)


def format_sites(doc: dict) -> str:
    if not doc.get("measured"):
        return "   места двери: НЕ ИЗМЕРЕНЫ — " + (doc.get("reason") or "причина не названа")
    counts = doc["counts"]
    body = " · ".join(f"{k} {counts[k]}" for k in DOOR_CLASSES)
    lines = [f"   места двери (файлов разобрано {doc['files_scanned']}): {body}"]
    if doc.get("files_unparsed"):
        lines.append(f"     НЕ РАЗОБРАНО файлов: {len(doc['files_unparsed'])} "
                     f"(первый: {doc['files_unparsed'][0]['file']})")
    if doc.get("sites_total", 0) == 0:
        lines.append("     измерено и равно нулю: ни одного вызова, гасящего срок")
    return "\n".join(lines)


def format_live(doc: dict) -> str:
    if not doc.get("measured"):
        return "   батарея двери: НЕ ИЗМЕРЕНА — " + (doc.get("reason") or "причина не названа")
    lines = [f"   батарея двери (срок {doc['deadline_s']:g} с, сцена живёт "
             f"{doc['over_s']:g} с): " +
             " · ".join(f"{k} {doc['counts'][k]}" for k in LIVE_VERDICTS)]
    for row in doc["rows"]:
        wall = row.get("wall_s")
        shown = "—" if wall is None else f"{wall:.1f} с"
        lines.append(f"     [{row['verdict']}] {shown} {row['case']} ({row['door']})"
                     + (f" — {row['reason']}" if row.get("reason") else ""))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Какая дверь пускает случай пережить `--timeout` (заказ G108 п. 2).")
    parser.add_argument("--stream", type=Path, default=None,
                        help="потоковая запись прогона: ось населения")
    parser.add_argument("--tree-root", type=Path, default=None,
                        help="корень дерева: ось мест двери")
    parser.add_argument("--battery", action="store_true",
                        help="прогнать живую батарею дочерним pytest")
    parser.add_argument("--deadline", type=float, default=2.0)
    parser.add_argument("--over", type=float, default=6.0)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    report: dict = {"schema": VERSION,
                    "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE)}
    printed = False
    unmeasured = False
    finding = False

    if args.stream is not None:
        doc = population_from_stream(args.stream)
        report["population"] = doc
        print(format_population(doc))
        printed = True
        unmeasured |= not doc.get("measured")
        finding |= bool(doc.get("measured") and (
            doc["counts"][CASE_SURVIVED] or doc["counts"][CASE_UNTERMINATED]))

    if args.tree_root is not None:
        doc = door_sites(args.tree_root)
        report["sites"] = doc
        print(format_sites(doc))
        printed = True
        unmeasured |= not doc.get("measured")
        finding |= bool(doc.get("measured") and doc.get("sites_total"))

    if args.battery:
        doc = live_door_verdicts(deadline_s=args.deadline, over_s=args.over)
        report["live"] = doc
        print(format_live(doc))
        printed = True
        unmeasured |= not doc.get("measured")
        finding |= bool(doc.get("measured") and doc["counts"][LIVE_DEFEATED])

    if args.json is not None:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    if not printed:
        print("НЕ ИЗМЕРЕНО: не задана ни одна ось "
              "(`--stream` / `--tree-root` / `--battery`)")
        return RC_UNMEASURED
    if unmeasured:
        return RC_UNMEASURED
    return RC_FINDING if finding else RC_MEASURED


if __name__ == "__main__":  # pragma: no cover - точка входа
    raise SystemExit(main())
