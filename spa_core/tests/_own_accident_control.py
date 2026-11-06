#!/usr/bin/env python3
"""spa_core/tests/_own_accident_control.py — ПРИБОР, НЕ ВИДЯЩИЙ СВОЕЙ АВАРИИ.

Вопрос, на который отвечает прибор
----------------------------------
«Сколько приборов дерева, спрошенных о дереве, в котором ВОССТАНОВЛЕНА их
СОБСТВЕННАЯ авария — та, ради которой прибор и написан, в её НАСТОЯЩЕМ месте, —
отвечают ТЕМ ЖЕ числом, что и о чистом дереве?»

Прибор, не изменивший своего ответа, отвечает о СВОЁМ ОХВАТЕ под видом ответа о
дереве. Это и есть предмет класса.

Откуда взят вопрос
------------------
Заказ **G921 п. 2** приказа владельца «Portfolio CIO» (хвост ADR-932), дословно:

    «Население класса "AST-прибор отвечает о СВОЁМ ОХВАТЕ под видом ответа о
     дереве" НЕ ИЗМЕРЕНО. Эта поправка закрыла дверь у ОДНОГО прибора; сколько
     других разбирают ОДНУ функцию и потому не видят предмет за её границей — не
     мерено, и нулём это не считается. Форма замера воспроизводима и дешева:
     ВОССТАНОВИТЬ в одноразовом дереве настоящую аварию, ради которой прибор
     написан, и спросить прибор. Прибор, не покрасневший на своей же аварии, и
     есть предмет класса.»

Класс найден не рассуждением, а дважды случившейся аварией:

* цикл #1046/#1047 (ADR-932): перепись класса «читатель режет вывод git по
  колонке, а дверь стрижёт» отвечала ``✅ ПУСТ`` при 19 зелёных тестах и 11/11
  убитых мутациях — и НЕ НАХОДИЛА аварию #1044 ни в одной из двух её форм,
  потому что разбирала ОДНУ функцию, а до двери было ДВА хопа через параметры;
* тот же цикл: сторож вакуума этой переписи («поверхность ≥ 3, стригущих
  дверей > 0») был ЗЕЛЁН и бесполезен — он считал ровно те срезы, которые
  прибор УМЕЛ видеть, то есть сам себя.

Почему мера ДИФФЕРЕНЦИАЛЬНАЯ, а не «красен ли прибор сегодня»
-------------------------------------------------------------
«Прибор красен» мерой не является: он может быть красен от ДРУГОЙ находки
живого дерева и при этом слеп к своей аварии (а может быть зелен потому, что
дерево чисто). Поэтому у каждой сцены снимается ДВА наблюдения одним и тем же
зовом — о ЧИСТОМ дереве и о дереве с восстановленной аварией, — и предметом
класса объявляется тот, у кого ОБЪЯВЛЕННОЕ ИМ ЖЕ число не изменилось.
Число берётся у прибора, а не придумывается здесь: имя ключа объявлено в сцене
(``signal_key``) и печатается рядом с вердиктом.

Род восстановления ОБЪЯВЛЕН — три рода, и они НЕ равносильны
------------------------------------------------------------
``history``
    байты взяты ДОСЛОВНО из истории (``git show <sha>^:<путь>``), место аварии —
    тот же путь. Сильнейший род: ни одна буква не придумана.
``record``
    текст аварии записан ДОСЛОВНО в самом дереве (докстринг прибора, ADR), и
    восстановлен в НАЗВАННОЕ там место. Слабее: место то же, байты вокруг —
    сегодняшние.
``constructed``
    у аварии нет ЕДИНСТВЕННОГО исторического места (класс был измерен, а не
    найден падением), поэтому форма класса воссоздана по его определению.
    Слабейший род, и он назван вслух: «зелено» под ним означает только «эту
    форму прибор не видит».

Смешать рода в одно число значило бы выдать воссозданную форму за настоящую
аварию — ровно тот дефект, который ADR-932 нашёл у СЕБЯ (``.claude`` память
«положительный контроль обязан быть НАСТОЯЩЕЙ аварией в её НАСТОЯЩЕМ месте»).

Три исхода, перечень ЗАКРЫТ, сумма равна населению (инв. #17)
-------------------------------------------------------------
``sees``        объявленное прибором число ВЫРОСЛО ⇒ свою аварию он видит.
``blind``       число НЕ ИЗМЕНИЛОСЬ ⇒ ПРЕДМЕТ КЛАССА.
``unmeasured``  восстановление не применилось · прибор не ответил · число ушло
                ВНИЗ (сцена возмутила не то, что объявляла). Это НЕ «чисто».

Почему он живёт в `spa_core/tests/`, а не в `scripts/`
------------------------------------------------------
Прибор ПРАВИТ дерево, на которое его направили, — значит ступенью цикла
(`findings_bridge`, шаг 0-офис) он быть не может ПО УСТРОЙСТВУ: ступень мерит
ЖИВОЕ дерево, а живое дерево этому прибору давать нельзя (отказ `guard_tree`).
Вызывающего по расписанию у него нет и не будет; его запускают рукой, как
`_subprocess_clock_door.py` (ADR-897) — соседа того же рода и той же семьи. Это
ОТВЕТ на вопрос заказа G921 п. 5 («прежде чем вставлять прибор в шаг, ответить,
от чего МОЖЕТ измениться его вердикт»), а не обход храповика
`test_unwired_scripts_ratchet`: тот сторожит `scripts/*.py`, и положить сюда
точку входа, которую никто не зовёт, было бы ровно тем дефектом, который он
ловит.

Что прибор НЕ доказывает
------------------------
* ``sees`` не означает «прибор видит ВСЕ формы своей аварии» — он видит ту,
  которая восстановлена. Вилка «одна форма … все формы» остаётся открытой;
  ADR-932 нашёл свою аварию именно во ВТОРОЙ форме.
* Перечень приборов ПОЛНЫМ не объявляется: он объявлен заказом G921 п. 2 как
  неполный, и дописывать в него надо сценой, а не именем.
* Прибор ничего не чинит и ничего не доставляет: он только ЧИТАЕТ приборы и
  правит ОДНОРАЗОВОЕ дерево, названное входом, возвращая байты побайтово.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
from typing import Callable, Optional

SEES = "sees"
BLIND = "blind"
UNMEASURED = "unmeasured"
OUTCOMES: tuple[str, ...] = (SEES, BLIND, UNMEASURED)

HISTORY = "history"
RECORD = "record"
CONSTRUCTED = "constructed"
RODS: tuple[str, ...] = (HISTORY, RECORD, CONSTRUCTED)

#: Прод-дерево. Править его этим прибором ЗАПРЕЩЕНО: там живёт состояние, и
#: «вернём как было» про него утверждать нельзя (`.claude/rules/deployment.md` п. 4).
PROD_ROOT = "/Users/yuriikulieshov/Documents/SPA_Claude"

#: Запись окна. Переживает SIGKILL — ровно поэтому несущая половина защиты это
#: ОНА, а не возврат в `finally` (урок ADR-772).
WINDOW_REL = ".own_accident_window/window.json"

DEFAULT_TIMEOUT_S = 2700

#: Дословный текст, которым сцена манифеста переносит привязку в прозу. Он же
#: её примета: в сегодняшних байтах его НЕТ, поэтому он что-то доказывает.
PROSE_MARK = "привязка перенесена в прозу сценой переписи: "


class Refused(Exception):
    """Отказ прибора: назван и печатается, кодом возврата 2."""


# ─────────────────────────────── сцены ───────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Edit:
    """Одна правка одноразового дерева.

    ``rel``             путь внутри дерева.
    ``source``          откуда взять байты: ``("history", "<sha>", "<путь>")``
                        либо ``("text", "<дословный текст>")`` либо
                        ``("sub", "<что>", "<на что>")`` — ТОЧНАЯ подстановка.
    """

    rel: str
    source: tuple


@dataclasses.dataclass(frozen=True)
class Scene:
    name: str
    instrument: str
    accident: str
    rod: str
    edits: tuple[Edit, ...]
    probe: tuple[str, ...]
    signal_key: str
    #: подстрока, которая ОБЯЗАНА появиться в восстановленных байтах
    marker_present: Optional[str] = None
    #: подстрока, которая ОБЯЗАНА из них исчезнуть
    marker_absent: Optional[str] = None
    #: второстепенные числа прибора, печатаются рядом, вердикта не решают
    also: tuple[str, ...] = ()
    #: сцена правит файл, которого в дереве ЕЩЁ НЕТ (создание)
    creates: tuple[str, ...] = ()


def _probe_injected_clock() -> tuple[str, ...]:
    """Зов измерителя претензии так, как его зовёт собственный сторож."""
    code = (
        "import json,sys,pathlib\n"
        "root=sys.argv[1]\n"
        "sys.path.insert(0,root)\n"
        "from spa_core.tests._injected_clock import claiming_files, measure_file, PROVEN\n"
        "fs=claiming_files(pathlib.Path(root)/'spa_core'/'tests')\n"
        "vs=[measure_file(f) for f in fs]\n"
        "print(json.dumps({'claiming':len(fs),\n"
        "  'not_proven':sum(1 for v in vs if v.verdict!=PROVEN)}))\n"
    )
    return (sys.executable, "-c", code, "{root}")


def _probe_substring() -> tuple[str, ...]:
    code = (
        "import json,sys\n"
        "root=sys.argv[1]\n"
        "sys.path.insert(0,root)\n"
        "from spa_core.monitoring.substring_structure_assertions import run\n"
        "d=run(root=root, write=False)\n"
        "print(json.dumps({'population':len(d['population']),\n"
        "  'findings':len(d['findings']),'status':d['status']}))\n"
    )
    return (sys.executable, "-c", code, "{root}")


#: Якорная пометка собирается СКЛЕЙКОЙ намеренно: дословная строка выписала бы
#: освобождение самому этому файлу (та же оговорка, что в `_injected_clock`).
_CLAIM = "# FROZEN-DATE" + "-OK: injected-clock — якорь уезжает входом"

#: Авария 2026-08-04 в той форме, которой её называет `.claude/rules/deployment.md`:
#: якорь уходит в КОНТЕЙНЕР, а контейнер привязкой НЕ является — то есть инъекции
#: нет вовсе, а записка о ней есть.
_SCENE_CONTAINER = f'''"""Сцена одноразового дерева: записка об инъекции БЕЗ инъекции.

{_CLAIM} — утверждение ЛОЖНО и ровно это здесь проверяется.
"""
import unittest
from datetime import datetime, timezone


def age_hours(doc, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(doc["generated_at"])
    return (now - stamp).total_seconds() / 3600.0


class TheContainerIsNotABinding(unittest.TestCase):
    def test_fresh(self):
        doc = {{"generated_at": datetime(2026, 8, 4, tzinfo=timezone.utc).isoformat()}}
        self.assertLess(age_hours(doc), 24.0)
'''

_SCENE_FORBIDDEN_HELPER = '''"""Сцена одноразового дерева: помощник, ввозящий запрещённую библиотеку."""
import requests  # noqa: F401 — предмет сцены


def fetch(url):
    return requests.get(url)
'''

_SCENE_FORBIDDEN_DOMAIN = '''"""Сцена одноразового дерева: файл ДОМЕНА ввозит запрещённое ЧЕРЕЗ помощника.

Прямой сторож (`scripts/lint_forbidden_imports.py`) здесь ничего не видит:
прямого импорта запрещённой библиотеки в файле нет.
"""
from spa_core.utils.zz_own_accident_helper import fetch


def ask(url):
    return fetch(url)
'''

#: Авария #567 ДОСЛОВНО из докстринга самого прибора
#: (`spa_core/monitoring/substring_structure_assertions.py`), в её названном месте —
#: приёмке шага 0-офис: слева начало кортежа, справа ТЕКСТ соседнего скрипта.
_SCENE_SUBSTRING = '''

class TheOfficeStepSchemaJudgedBySubstring(unittest.TestCase):
    """Авария #567, восстановленная в её НАСТОЯЩЕМ месте (ADR-333/ADR-338).

    Снятие ключа `blindness` из кортежа оставляет эту проверку ЗЕЛЁНОЙ: подстрока
    обрывается на `"counts",` и о том, что стои́т за ней, не знает ничего.
    """

    def test_office_step_declares_the_schema(self):
        src = (_ROOT / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        self.assertIn('"subject_population_census.json": ("status", "counts",', src)
'''


def _probe_prose() -> tuple[str, ...]:
    """Зов переписи привязок. Числа — её собственные исходы из `rows[].place`."""
    code = (
        "import json,sys\n"
        "root=sys.argv[1]\n"
        "sys.path.insert(0,root)\n"
        "from spa_core.monitoring.prose_binding_census import measure\n"
        "import pathlib\n"
        "d=measure(pathlib.Path(root))\n"
        "pl=[r['place'] for r in d['rows']]\n"
        "print(json.dumps({'field_bypassed':pl.count('field_bypassed'),\n"
        "  'both':pl.count('both'),'on_prose':d['on_prose'],\n"
        "  'population':d['population']}))\n"
    )
    return (sys.executable, "-c", code, "{root}")


def _scenes() -> tuple[Scene, ...]:
    return (
        Scene(
            name="git_column_door_census",
            instrument="scripts/git_column_door_census.py",
            accident=(
                "#1044/ADR-932: читатель режет вывод git ПО КОЛОНКЕ, а дверь `_git` "
                "стрижёт ведущий пробел — `unparsed.append(line[:60])` в "
                "`orphan_sweep.worktree_door()`. Прибор первой редакции не видел её "
                "НИ В ОДНОЙ из двух форм (до двери ДВА хопа через параметры)."
            ),
            rod=HISTORY,
            edits=(Edit("spa_core/monitoring/orphan_sweep.py",
                        ("sub", "unparsed.append(repr(line)[:60])",
                         "unparsed.append(line[:60])")),),
            probe=(sys.executable, "{root}/scripts/git_column_door_census.py",
                   "--root", "{root}", "--json"),
            signal_key="bomb",
            marker_present="unparsed.append(line[:60])",
            also=("surface", "doors", "unmeasured"),
        ),
        Scene(
            name="subprocess_clock_door",
            instrument="spa_core/tests/_subprocess_clock_door.py",
            accident=(
                "#1010/ADR-897: файл выписал себе претензию `injected-clock`, а ВТОРАЯ "
                "сторона сравнения жила в ДРУГОМ процессе — производитель "
                "`refresh_no_regression_census.py` спрашивал «сколько сейчас» у стенных "
                "часов. 31.10 пять проверок покраснели ОТ КАЛЕНДАРЯ при неизменных "
                "байтах кода."
            ),
            rod=HISTORY,
            edits=(Edit("spa_core/tests/test_no_regression_producer_wiring.py",
                        ("history", "539bccdd4^",
                         "spa_core/tests/test_no_regression_producer_wiring.py")),),
            probe=(sys.executable, "{root}/spa_core/tests/_subprocess_clock_door.py",
                   "--repo-root", "{root}", "--json"),
            signal_key="anchor_not_passed",
            marker_absent='"--now", NOW.isoformat()',
            also=("on_surface", "anchor_passed", "claiming_files"),
        ),
        Scene(
            name="substring_structure_assertions",
            instrument="spa_core/monitoring/substring_structure_assertions.py",
            accident=(
                "#567/ADR-333: утверждение судило СТРУКТУРУ соседа по ПОДСТРОКЕ её "
                "сериализованного вида — `assertIn('\"subject_population_census.json\": "
                "(\"status\", \"counts\",', src)` в приёмке шага 0-офис; снятие ключа "
                "`blindness` за концом литерала оставляло проверку ЗЕЛЁНОЙ."
            ),
            rod=RECORD,
            edits=(Edit("spa_core/tests/test_subject_population_census.py",
                        ("append", _SCENE_SUBSTRING)),),
            probe=_probe_substring(),
            signal_key="population",
            # Примета — ФОРМА УТВЕРЖДЕНИЯ, а не литерал: сам литерал стои́т в
            # сегодняшнем докстринге того же файла (там он ОБЪЯСНЯЕТ аварию), и
            # примета-литерал оказалась ВАКУУМНОЙ — отказ по вакуумной примете
            # это и показал.
            marker_present=(
                "self.assertIn('\"subject_population_census.json\": "
                "(\"status\", \"counts\",', src)"),
            also=("findings",),
        ),
        Scene(
            name="injected_clock",
            instrument="spa_core/tests/_injected_clock.py",
            accident=(
                "2026-08-04 (`.claude/rules/deployment.md`): файл выписал себе "
                "освобождение `injected-clock`, а якорь ушёл в КОНТЕЙНЕР "
                "(`doc = {\"generated_at\": …}` рядом с `age_hours(doc)`) — контейнер "
                "привязкой НЕ является, инъекции нет вовсе, записка о ней есть."
            ),
            rod=CONSTRUCTED,
            edits=(Edit("spa_core/tests/test_zz_own_accident_container_scene.py",
                        ("text", _SCENE_CONTAINER)),),
            probe=_probe_injected_clock(),
            signal_key="not_proven",
            marker_present="age_hours(doc)",
            also=("claiming",),
            creates=("spa_core/tests/test_zz_own_accident_container_scene.py",),
        ),
        Scene(
            name="forbidden_reach_census",
            instrument="scripts/forbidden_reach_census.py",
            accident=(
                "Заказ G107 п. 3 / ADR-529: файл объявленного РАНТАЙМ-ДОМЕНА ввозит "
                "запрещённую библиотеку ЧЕРЕЗ ПОМОЩНИКА, то есть так, что прямой "
                "сторож `lint_forbidden_imports` не видит этого ни одной своей формой."
            ),
            rod=CONSTRUCTED,
            edits=(Edit("spa_core/utils/zz_own_accident_helper.py",
                        ("text", _SCENE_FORBIDDEN_HELPER)),
                   Edit("spa_core/monitoring/zz_own_accident_domain_scene.py",
                        ("text", _SCENE_FORBIDDEN_DOMAIN))),
            probe=(sys.executable, "{root}/scripts/forbidden_reach_census.py",
                   "--root", "{root}", "--json", "--no-cache"),
            signal_key="counts.brought_in_through_helper",
            marker_present="from spa_core.utils.zz_own_accident_helper import fetch",
            also=("counts.brought_in_directly", "domain_files", "population"),
            creates=("spa_core/utils/zz_own_accident_helper.py",
                     "spa_core/monitoring/zz_own_accident_domain_scene.py"),
        ),
        Scene(
            name="prose_binding_census",
            instrument="spa_core/monitoring/prose_binding_census.py",
            accident=(
                "ADR-506/заказ G94 п. 3: привязка записи конституции названа ПРОЗОЙ "
                "(`notes`) при том, что поле `governed_by` у этого рода ЕСТЬ и пусто — "
                "читатель поля слеп к записи уже сегодня (`field_bypassed`)."
            ),
            rod=CONSTRUCTED,
            edits=(Edit("architecture/manifest.json", ("prose_bypass",)),),
            probe=_probe_prose(),
            signal_key="field_bypassed",
            marker_present=PROSE_MARK,
            also=("on_prose", "population", "both"),
        ),
    )


# ─────────────────────────── правка дерева ───────────────────────────────────


def _git(repo: str, *args: str) -> str:
    """Голос git о дереве. Вывод НЕ обрезается: ведущий пробел значим (ADR-932)."""
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise Refused(f"git {' '.join(args)} в {repo}: {out.stderr.strip()}")
    return out.stdout


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _prose_bypass(root: pathlib.Path) -> bytes:
    """Воссоздать `field_bypassed`: перенести привязку из ПОЛЯ в ПРОЗУ.

    Запись выбирается ДЕТЕРМИНИРОВАННО и с доказанной предпосылкой: поле
    `governed_by` называет ADR, которого в `notes` ЕЩЁ НЕТ. Иначе место записи и
    так `both` (привязка уже в прозе), перенос не меняет НИ ОДНОГО объявленного
    числа, и сцена молча померила бы не то — замер этого цикла.
    """
    path = root / "architecture" / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    agents = doc.get("agents")
    if not isinstance(agents, list):
        raise Refused("в манифесте нет раздела `agents` списком — "
                      "сцена `prose_bypass` свою предпосылку не обеспечила")
    import re as _re
    for row in agents:
        if not isinstance(row, dict):
            continue
        bound = row.get("governed_by")
        names = [bound] if isinstance(bound, str) else list(bound or [])
        adrs = [str(x) for x in names if _re.fullmatch(r"ADR-\d+", str(x))]
        note = str(row.get("notes") or "")
        fresh = [a for a in adrs if a not in note]
        if len(adrs) != len(names) or not fresh or len(adrs) != 1:
            continue
        row["notes"] = (note + " " if note else "") + PROSE_MARK + adrs[0]
        row["governed_by"] = "" if isinstance(bound, str) else []
        return json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    raise Refused("ни одна запись агента манифеста не несёт РОВНО ОДНУ привязку-ADR, "
                  "которой нет в прозе — сцена свою предпосылку НЕ обеспечила")


def _restored_bytes(root: pathlib.Path, edit: Edit, before: Optional[bytes]) -> bytes:
    kind = edit.source[0]
    if kind == "text":
        return edit.source[1].encode("utf-8")
    if kind == "append":
        if before is None:
            raise Refused(f"{edit.rel}: дописывать некуда — файла в дереве нет")
        return before + edit.source[1].encode("utf-8")
    if kind == "sub":
        if before is None:
            raise Refused(f"{edit.rel}: подстановка невозможна — файла в дереве нет")
        old, new = edit.source[1], edit.source[2]
        text = before.decode("utf-8")
        if text.count(old) != 1:
            raise Refused(
                f"{edit.rel}: подстрока аварии встречается {text.count(old)} раз(а), "
                f"а не один — сцена НЕ применена (это «не измерено», не «чисто»)")
        return text.replace(old, new, 1).encode("utf-8")
    if kind == "history":
        sha, rel = edit.source[1], edit.source[2]
        out = subprocess.run(["git", "-C", str(root), "show", f"{sha}:{rel}"],
                             capture_output=True)
        if out.returncode != 0:
            raise Refused(f"{rel}@{sha}: история не отдала байты "
                          f"({out.stderr.decode('utf-8', 'replace').strip()})")
        return out.stdout
    if kind == "prose_bypass":
        return _prose_bypass(root)
    raise Refused(f"неизвестный род правки: {kind}")


# ─────────────────────────── зов прибора ─────────────────────────────────────


def _dig(doc: dict, key: str):
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _ask(scene: Scene, root: pathlib.Path, timeout_s: int) -> dict:
    """Спросить прибор о дереве. Ответ прибора — ЕГО число, не наше суждение."""
    argv = [a.replace("{root}", str(root)) for a in scene.probe]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONHASHSEED"] = "0"
    started = time.time()
    try:
        out = subprocess.run(argv, capture_output=True, text=True, cwd=str(root),
                             env=env, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"answered": False, "reason": f"прибор не ответил за {timeout_s} с",
                "seconds": round(time.time() - started, 1)}
    took = round(time.time() - started, 1)
    doc = None
    for line in reversed(out.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                doc = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if doc is None:
        try:
            doc = json.loads(out.stdout)
        except Exception:  # noqa: BLE001
            doc = None
    if doc is None:
        return {"answered": False, "seconds": took, "exit": out.returncode,
                "reason": "ответ прибора не разобран как JSON: "
                          + (out.stdout[-300:] or out.stderr[-300:]).strip()}
    signal = _dig(doc, scene.signal_key)
    if not isinstance(signal, (int, float)):
        return {"answered": False, "seconds": took, "exit": out.returncode,
                "reason": f"объявленного числа `{scene.signal_key}` в ответе нет"}
    return {"answered": True, "seconds": took, "exit": out.returncode,
            "signal": signal,
            "also": {k: _dig(doc, k) for k in scene.also}}


# ─────────────────────────── окно и дерево ───────────────────────────────────


def _window_path(root: pathlib.Path) -> pathlib.Path:
    return root / WINDOW_REL


def _open_window(root: pathlib.Path, scene: str) -> None:
    p = _window_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "pid": os.getpid(), "hostname": socket.gethostname(), "scene": scene,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": "spa_core/tests/_own_accident_control.py",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _close_window(root: pathlib.Path) -> None:
    p = _window_path(root)
    if p.exists():
        p.unlink()
    try:
        p.parent.rmdir()
    except OSError:
        pass


def guard_tree(root: pathlib.Path) -> None:
    """Отказы ДО первой правки. Молчаливого пути сюда нет."""
    if not root.exists():
        raise Refused(f"дерево {root} не существует")
    real = os.path.realpath(str(root))
    if real == os.path.realpath(PROD_ROOT):
        raise Refused(
            f"названо ПРОД-дерево {real}: прибор правит файлы НА МЕСТЕ, а в проде "
            "живёт состояние — «вернём как было» про него утверждать нельзя "
            "(.claude/rules/deployment.md п. 4)")
    own = os.path.realpath(str(pathlib.Path(__file__).resolve().parents[2]))
    if real == own:
        raise Refused(
            f"названо дерево САМОГО прибора {real}: долгий прогон не живёт в дереве "
            "доставки (.claude/rules/deployment.md § «БАЙТЫ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ "
            "КОДОМ», п. 1)")
    if not (root / ".git").exists():
        raise Refused(f"{real} не является рабочим деревом git — вернуть байты "
                      "и сверить их будет нечем")
    win = _window_path(root)
    if win.exists():
        raise Refused(f"в дереве ОТКРЫТО окно прошлого прогона: {win} — "
                      f"{win.read_text(encoding='utf-8')[:400]}")
    raw = _git(str(root), "status", "--porcelain")
    dirty = [ln[3:] for ln in raw.split("\n") if ln and not ln[3:].startswith("data/")]
    if dirty:
        raise Refused(
            f"дерево несёт {len(dirty)} незакоммиченных пут(ь/и) вне `data/` "
            f"(например {dirty[:3]}) — побайтовый возврат сцены доказать нечем")


# ─────────────────────────── одна сцена ──────────────────────────────────────


def run_scene(scene: Scene, root: pathlib.Path, timeout_s: int,
              say: Callable[[str], None]) -> dict:
    row: dict = {"name": scene.name, "instrument": scene.instrument,
                 "rod": scene.rod, "signal_key": scene.signal_key,
                 "accident": scene.accident}
    before: dict[str, Optional[bytes]] = {}
    for e in scene.edits:
        p = root / e.rel
        before[e.rel] = p.read_bytes() if p.exists() else None
    pre_sha = {rel: (_sha(b) if b is not None else None) for rel, b in before.items()}

    say(f"[сцена] {scene.name}: базовый зов прибора…")
    base = _ask(scene, root, timeout_s)
    row["base"] = base
    if not base["answered"]:
        row["outcome"] = UNMEASURED
        row["reason"] = "о ЧИСТОМ дереве прибор не ответил: " + base["reason"]
        return row

    restored: dict[str, bytes] = {}
    try:
        for e in scene.edits:
            restored[e.rel] = _restored_bytes(root, e, before[e.rel])
    except Refused as exc:
        row["outcome"] = UNMEASURED
        row["reason"] = f"восстановление не применилось: {exc}"
        return row

    for rel, data in restored.items():
        if before.get(rel) == data:
            row["outcome"] = UNMEASURED
            row["reason"] = (f"{rel}: восстановленные байты РАВНЫ сегодняшним — "
                             "сцена ничего не возмутила")
            return row

    blob = b"".join(restored.values()).decode("utf-8", "replace")
    was = b"".join(v for v in before.values() if v is not None).decode("utf-8", "replace")
    if scene.marker_present and scene.marker_present in was:
        row["outcome"] = UNMEASURED
        row["reason"] = (f"примета аварии `{scene.marker_present[:60]}` ЕСТЬ и в "
                         "сегодняшних байтах — она ничего не доказывает (ВАКУУМНАЯ "
                         "примета), вердикт о классе не выдаётся")
        return row
    if scene.marker_absent and scene.marker_absent not in was:
        row["outcome"] = UNMEASURED
        row["reason"] = (f"примета починки `{scene.marker_absent[:60]}` в сегодняшних "
                         "байтах ОТСУТСТВУЕТ — снимать нечего, вердикт не выдаётся")
        return row
    if scene.marker_present and scene.marker_present not in blob:
        row["outcome"] = UNMEASURED
        row["reason"] = (f"в восстановленных байтах НЕТ приметы аварии "
                         f"`{scene.marker_present[:60]}` — восстановлено не то")
        return row
    if scene.marker_absent and scene.marker_absent in blob:
        row["outcome"] = UNMEASURED
        row["reason"] = (f"в восстановленных байтах ОСТАЛАСЬ примета починки "
                         f"`{scene.marker_absent[:60]}` — авария не восстановлена")
        return row

    _open_window(root, scene.name)
    try:
        for rel, data in restored.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        say(f"[сцена] {scene.name}: авария восстановлена ({scene.rod}), "
            f"зов прибора о ней…")
        after = _ask(scene, root, timeout_s)
    finally:
        # Возврат байтов НЕ ИМЕЕТ ПРАВА упасть молча: неудачная запись и
        # разошедшийся sha — ОДИН исход («дерево остаётся изменённым»), и назвать
        # его обязан прибор, а не следующий читатель дерева. Прогон под прибором
        # способен подменить сам путь (замер ADR-886: тест правил исходники НА
        # МЕСТЕ), поэтому ошибка записи здесь ожидаемая, а не невозможная.
        failed: list[str] = []
        for rel, data in before.items():
            p = root / rel
            try:
                if data is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.write_bytes(data)
            except OSError as exc:  # noqa: PERF203 — исход, а не аварийный путь
                failed.append(f"{rel}: {type(exc).__name__}: {exc}")
        back = {}
        for rel in before:
            p = root / rel
            try:
                back[rel] = _sha(p.read_bytes()) if p.exists() else None
            except OSError as exc:  # noqa: BLE001 — нечитаемость это исход
                back[rel] = f"НЕ ПРОЧИТАН: {type(exc).__name__}"
        _close_window(root)
        # `failed or` — ВТОРАЯ ДВЕРЬ к одному наблюдению, и это измерено, а не
        # предположено: мутант, снимающий её, ЭКВИВАЛЕНТЕН на каждой сцене набора
        # (неудачная запись всегда оставляет и разошедшийся sha). Расходятся они
        # ровно в одном состоянии — запись не удалась, а байты и так равны
        # пред-образу, — и там отказ говорит «восстановить не удалось», что
        # ВЕРНО по существу. Сцены на это состояние НЕ ВЫДУМАНО намеренно.
        if failed or back != pre_sha:
            raise Refused(
                f"сцена {scene.name}: байты НЕ ВЕРНУЛИСЬ побайтово "
                f"(до {pre_sha} после {back}"
                + (f"; запись не удалась: {failed}" if failed else "")
                + ") — дерево остаётся изменённым, и молчать об этом нельзя")

    row["restored"] = after
    if not after["answered"]:
        row["outcome"] = UNMEASURED
        row["reason"] = "о дереве с аварией прибор не ответил: " + after["reason"]
        return row

    b, a = base["signal"], after["signal"]
    row["delta"] = a - b
    if a > b:
        row["outcome"] = SEES
        row["reason"] = f"`{scene.signal_key}` {b} → {a}: свою аварию прибор НАЗЫВАЕТ"
    elif a == b:
        row["outcome"] = BLIND
        row["reason"] = (f"`{scene.signal_key}` не изменилось ({b}): прибор ответил о "
                         "СВОЁМ ОХВАТЕ, а не о дереве — ПРЕДМЕТ КЛАССА")
    else:
        row["outcome"] = UNMEASURED
        row["reason"] = (f"`{scene.signal_key}` УПАЛО {b} → {a}: сцена возмутила не то, "
                         "что объявляла, и вердикт о классе не выдаётся")
    return row


# ─────────────────────────── отчёт ───────────────────────────────────────────


def report(doc: dict) -> list[str]:
    out = [f"перепись «прибор, не видящий своей аварии»: население {doc['population']}, "
           f"дерево {doc['repo_root']}"]
    c = doc["counts"]
    out.append(f"   исходы: видит {c[SEES]} · СЛЕП {c[BLIND]} · "
               f"НЕ ИЗМЕРЕНО {c[UNMEASURED]} (сумма {sum(c.values())} = населению)")
    by_rod = doc["by_rod"]
    out.append("   род восстановления: " + " · ".join(
        f"{rod} {by_rod.get(rod, {}).get('total', 0)}"
        f" (видит {by_rod.get(rod, {}).get(SEES, 0)},"
        f" слеп {by_rod.get(rod, {}).get(BLIND, 0)})" for rod in RODS))
    for row in doc["rows"]:
        mark = {SEES: "✅", BLIND: "💣", UNMEASURED: "❔"}[row["outcome"]]
        out.append(f"   {mark} {row['name']} [{row['rod']}] — {row['reason']}")
        if row.get("base", {}).get("also"):
            out.append(f"        рядом: {row['base']['also']} → "
                       f"{row.get('restored', {}).get('also')}")
        secs = (row.get("base", {}).get("seconds"), row.get("restored", {}).get("seconds"))
        out.append(f"        ⏱ базовый зов {secs[0]} с · зов об аварии {secs[1]} с")
    out.append("   ОГОВОРКА: «видит» означает «видит ВОССТАНОВЛЕННУЮ форму», а не все "
               "формы своей аварии — ADR-932 нашёл свою во ВТОРОЙ форме.")
    out.append("   ADVISORY: прибор только ЧИТАЕТ приборы и правит ОДНОРАЗОВОЕ дерево, "
               "названное входом; байты возвращены и сверены sha256.")
    return out


def measure(repo_root: str, only: Optional[list[str]] = None,
            timeout_s: int = DEFAULT_TIMEOUT_S,
            say: Callable[[str], None] = lambda s: None,
            scenes: Optional[tuple[Scene, ...]] = None) -> dict:
    """ЗАМЕР. Сцены подаются входом, чтобы приёмка могла предъявить прибору
    ЗАВЕДОМО СЛЕПОЙ прибор: перепись, умеющая отвечать только «видит», отвечала
    бы о своём охвате — ровно то, что она измеряет у других."""
    root = pathlib.Path(repo_root).resolve()
    guard_tree(root)
    scenes = scenes if scenes is not None else _scenes()
    if only:
        known = {s.name for s in scenes}
        unknown = sorted(set(only) - known)
        if unknown:
            raise Refused(f"сцены с именами {unknown} нет; есть {sorted(known)}")
        scenes = tuple(s for s in scenes if s.name in set(only))
    rows = [run_scene(s, root, timeout_s, say) for s in scenes]
    counts = {o: sum(1 for r in rows if r["outcome"] == o) for o in OUTCOMES}
    by_rod: dict[str, dict] = {}
    for r in rows:
        slot = by_rod.setdefault(r["rod"], {o: 0 for o in OUTCOMES} | {"total": 0})
        slot[r["outcome"]] += 1
        slot["total"] += 1
    return {
        "question": ("сколько приборов, спрошенных о дереве с ВОССТАНОВЛЕННОЙ их "
                     "собственной аварией, отвечают ТЕМ ЖЕ числом"),
        "order": "G921 п. 2 (приказ владельца Portfolio CIO, хвост ADR-932)",
        "repo_root": str(root),
        "ref": _git(str(root), "rev-parse", "HEAD").strip(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "population": len(rows),
        "counts": counts,
        "counts_sum": sum(counts.values()),
        "by_rod": by_rod,
        "outcomes_declared": list(OUTCOMES),
        "rods_declared": list(RODS),
        "roster_is_not_complete": ("перечень приборов объявлен заказом G921 п. 2 как "
                                   "НЕПОЛНЫЙ; дописывать в него надо СЦЕНОЙ"),
        "rows": rows,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", required=True,
                    help="ОДНОРАЗОВОЕ дерево: прибор правит файлы НА МЕСТЕ")
    ap.add_argument("--only", nargs="*", default=None, help="прогнать ровно эти сцены")
    ap.add_argument("--list", action="store_true", help="печатать сцены и выйти")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None, help="куда записать замер")
    a = ap.parse_args(argv)

    if a.list:
        for s in _scenes():
            print(f"{s.name} [{s.rod}] → {s.instrument} (число `{s.signal_key}`)")
        return 0

    say = (lambda s: print(s, file=sys.stderr, flush=True))
    try:
        doc = measure(a.repo_root, a.only, a.timeout, say)
    except Refused as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        print("  про класс «прибор, не видящий своей аварии» НЕ СКАЗАНО НИЧЕГО")
        return 2
    if a.out:
        pathlib.Path(a.out).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in report(doc):
            print(line)
    if doc["counts"][UNMEASURED]:
        return 2
    return 1 if doc["counts"][BLIND] else 0


if __name__ == "__main__":
    sys.exit(main())
