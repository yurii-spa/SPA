#!/usr/bin/env python3
"""scripts/check_concurrent_pytest.py — automates a manual pre-run ritual.

**Two different hazards, documented separately in the journal, conflated in
practice.**

1. **Same working tree, multiple pytest processes** — confirmed DATA
   CORRUPTION (cycle #352, 23.08): three runs in one tree wrote over each
   other's ``data/``. Any acceptance number from such a run is worthless.
   ``pkill -f "<tree-path>"`` does NOT catch these — the tree path lives in
   the process's ``cwd``, not its command line (``python3 -m pytest
   spa_core/tests/ …`` never mentions the tree). Identify by ``lsof -d cwd``.

2. **A run whose requester is dead** — the session that ordered the run died,
   its ``pytest`` did not: the process reparents to ``init`` (``ppid == 1``)
   and keeps burning a core for hours on a result **nobody will ever read**.
   Measured six times in the 24h of 27–28.08 (cycles #398, #401 ×2, #408,
   #415 ×2, #417); the #417 one had spent 64 minutes of CPU. They starve the
   living: cycle #406 could not finish its own acceptance run because two
   such corpses held the machine.

   ``ppid == 1`` **alone does not mean orphaned** — that is the trap this
   check has to avoid, because every backgrounded run (``nohup … &``) also
   reparents to ``init`` the moment its shell exits, and those runs are very
   much awaited. The requester is therefore measured, not guessed: the tree
   the process sits in is looked up in the announce log
   (``data/session_changes.jsonl``) and the announcing session's durable
   process is probed with the same code step 0a uses. Dead ⇒ ORPHAN. Alive ⇒
   ATTENDED. No announcement, or no durable process declared ⇒ **UNMEASURED**,
   which is not "orphan" — an unnamed requester is not a dead one, and this
   check will not send anyone to kill a process on a guess.

   **Known limit, named rather than papered over:** the tree→session link is
   only readable when the session announced ABSOLUTE paths
   (``/tmp/spa_c416/spa_core/x.py``). ``worktree_of`` refuses to infer a root
   from a relative path — guessing there would be a measurement in name only.
   A session that announced relative paths therefore gets UNMEASURED, not
   ORPHAN. Measured live on the real log at the moment of writing: the corpse
   of cycle #416 (``pid 27998``, ``/tmp/spa_c416``, 64 min of CPU) is named
   ORPHAN with its dead requester ``cycle-14573``; two other dead trees come
   back UNMEASURED because nobody announced them in absolute form.

3. **Different working trees, concurrent full runs** — NOT always harmful.
   Measured BOTH ways: cycle #347 ran two full suites (own tree + a pinned
   control) at once and both finished in ~22 min, same as running one alone.
   Cycle #377 ran two full suites at once and both starved to ~7 tests per
   10 minutes at the 93% mark. The difference is not understood; a hard lock
   here would sometimes throw away real parallelism for no reason, so this
   stays advisory.

This script is a READ-ONLY pre-flight check: it never kills a process, never
blocks a run, and never writes anything. It answers "what pytest processes
are running right now, and do any of them share MY cwd" so a human (or an
autonomous session) can decide before trusting a run's result.

CLI::
    python3 scripts/check_concurrent_pytest.py            # check own cwd
    python3 scripts/check_concurrent_pytest.py --json
    python3 scripts/check_concurrent_pytest.py --cwd /path/to/tree

Exit codes: 0 = clear (no same-cwd collision, no confirmed orphan); 1 =
same-cwd collision found (hazard #1 — treat any prior/concurrent run in this
tree as untrustworthy); 2 = could not enumerate processes (fail-CLOSED: treat
as "unmeasured", not "clear"); 3 = no collision, but at least one CONFIRMED
orphaned run is burning a core (hazard #2). Collision outranks orphan: 1 is
about the trustworthiness of YOUR number, 3 only about the machine.

Why an orphan gets its own code instead of a printed line: exit 0 means
"clear", and a machine-starving corpse is not clear. A finding that only ever
appears in prose is a finding whose reader is optional — which is how this
class survived six recurrences in a day.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


#: Три исхода вопроса «этот прогон ещё кому-то нужен?». Второй и третий
#: разделены намеренно: «заказчик мёртв» и «заказчика не назвали» — не одно и
#: то же, и на догадке никого убивать нельзя.
ORPHAN = "orphan"
ATTENDED = "attended"
UNMEASURED = "unmeasured"

#: Родитель осиротевшего процесса на macOS — launchd. Признак НЕОБХОДИМЫЙ и
#: заведомо НЕ достаточный: любой `nohup … &` получает ppid=1, как только его
#: оболочка завершилась, и такие прогоны ждут.
INIT_PPID = 1

_SIBLING = Path(__file__).resolve().parent / "check_undelivered_work.py"
_SIBLING_MOD = ...


def _owner_probe():
    """Сосед `check_undelivered_work` или None — загружается один раз.

    Он владеет разбором `ps`/`lstart`, чтением журнала объявлений и ответом на
    «жив ли долгоживущий процесс сессии». Своя копия этих ответов была бы тем
    самым близнецом, которого проект уже ловил: одну копию чинят, вторая лежит.
    None (файла нет / импорт сломан) — тоже измерение: вердикт станет
    UNMEASURED, а не «сирот нет»."""
    global _SIBLING_MOD
    if _SIBLING_MOD is ...:
        try:
            spec = importlib.util.spec_from_file_location("_ccp_owner", _SIBLING)
            if spec is None or spec.loader is None:
                _SIBLING_MOD = None
            else:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _SIBLING_MOD = mod
        except (OSError, ImportError, SyntaxError, AttributeError, ValueError, TypeError):
            _SIBLING_MOD = None
    return _SIBLING_MOD


@dataclass
class PytestProc:
    pid: int
    lstart: str
    command: str
    cwd: str | None = None
    ppid: int | None = None
    orphan: str | None = None       # ORPHAN / ATTENDED / UNMEASURED
    orphan_why: str | None = None


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def list_pytest_processes(*, self_pid: int | None = None) -> list[PytestProc] | None:
    """Enumerate running pytest processes system-wide. ``None`` = unmeasured."""
    raw = _run(["ps", "-ax", "-o", "pid=,ppid=,lstart=,command="])
    if raw is None:
        return None
    procs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        rest = parts[2]
        # lstart is a fixed-width ctime-style string (e.g. "Thu Aug 28 10:00:00 2026")
        # followed by the command — split on that convention: 5 tokens of lstart.
        rest_tokens = rest.split(None, 5)
        if len(rest_tokens) < 6:
            continue
        lstart = " ".join(rest_tokens[:5])
        command = rest_tokens[5]
        if "pytest" not in command:
            continue
        if self_pid is not None and pid == self_pid:
            continue
        if "check_concurrent_pytest" in command:
            continue  # never report ourselves or a sibling invocation of this tool
        procs.append(PytestProc(pid=pid, ppid=ppid, lstart=lstart, command=command))
    return procs


def resolve_cwd(pid: int) -> str | None:
    """Resolve a process's working directory via lsof (cmdline path is unreliable —
    see pkill-by-path-misses-pytest: the tree path lives in cwd, not argv)."""
    raw = _run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    if raw is None:
        return None
    for line in raw.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def _announce_log(owner):
    """Журнал объявлений ГЛАВНОГО рабочего дерева, либо None.

    Найдено живым прогоном (цикл #417), а не рассуждением: проверка идёт из
    одноразового worktree, `data/` в git не лежит, и путь «рядом с этим файлом»
    указывает на несуществующий файл. Тогда КАЖДЫЙ процесс получал вердикт
    «журнал не прочитан» — формально честный третий исход, практически
    бесполезный: сирота и живой прогон становились неотличимы.

    Резолв — тот же, что у `log_session_change` (`shared_log`): один ответ на
    вопрос «где общее состояние». Не разрешилось ⇒ None ⇒ UNMEASURED."""
    if owner is None:
        return None
    try:
        path, _err = owner.shared_log()
    except (OSError, AttributeError, ValueError, TypeError):
        return None
    return path


def classify_orphan(proc: PytestProc, *, owner=..., entries=None) -> tuple[str, str]:
    """(ORPHAN|ATTENDED|UNMEASURED, чем измерено) для ОДНОГО процесса.

    Порядок вопросов — от самого дешёвого отказа к самому дорогому измерению, и
    ни один шаг не имеет права ответить ORPHAN по умолчанию:

    1. ``ppid != 1`` ⇒ ATTENDED. Родитель жив — процесс кто-то держит.
    2. ``cwd`` не разрешён ⇒ UNMEASURED. Без дерева нет и заказчика.
    3. Дерево не объявлено в журнале ⇒ UNMEASURED. Отсутствие объявления —
       это про журнал, а не про жизнь сессии.
    4. Объявление есть: спрашиваем СОСЕДА (`durable_process_gone`), который
       отвечает True только на ИЗМЕРЕННОЕ исчезновение объявленного
       долгоживущего процесса. Его «не знаю» приходит сюда как UNMEASURED, а
       не как смерть."""
    if owner is ...:
        owner = _owner_probe()
    if proc.ppid is not None and proc.ppid != INIT_PPID:
        return ATTENDED, f"родитель жив (ppid={proc.ppid}) — процесс кто-то держит"
    if proc.ppid is None:
        return UNMEASURED, "ppid не прочитан"
    if not proc.cwd:
        return UNMEASURED, "дерево процесса не разрешено (lsof недоступен) — заказчика не найти"
    if owner is None:
        return UNMEASURED, "сосед check_undelivered_work не загрузился — живость сессии нечем мерить"

    tree = owner.tree_of_path(os.path.join(proc.cwd, "spa_core"))
    if not tree:
        tree = os.path.realpath(proc.cwd)
    if entries is None:
        log = _announce_log(owner)
        if log is None:
            return UNMEASURED, "журнал объявлений не найден (главное дерево не разрешено)"
        try:
            entries, _bad = owner.read_entries(log, None)
        except (OSError, ValueError, TypeError):
            return UNMEASURED, f"журнал объявлений не прочитан ({log})"

    mine = [e for e in (entries or ()) if owner.worktree_of(e) == tree]
    if not mine:
        return UNMEASURED, (f"дерево {tree} не объявлено в журнале — заказчик НЕ НАЗВАН; "
                            f"это не «мёртв», а «не измерено»")

    # НЕ «последняя запись», а последняя, НАЗВАВШАЯ долгоживущий процесс.
    # Найдено живым прогоном (#417): поверх собственного объявления с
    # `session_pid` сессия пишет короткие служебные записи (захват карточки), у
    # которых долгоживущего процесса нет по построению — `session` там pid
    # ОДНОКРАТНОЙ CLI-команды. Взяв просто последнюю, проверка теряла
    # единственное измеримое свидетельство и на живом прогоне отвечала «не
    # измерено». Ответ был честным и бесполезным: сирота и живой прогон
    # становились неотличимы, то есть проверка молчала ровно там, где нужна.
    latest = next((e for e in reversed(mine) if e.get("session_pid")), mine[-1])
    if owner.durable_process_gone(latest):
        return ORPHAN, (f"дерево {tree} объявила сессия `{latest.get('session')}`, её "
                        f"долгоживущий процесс pid{latest.get('session_pid')} ИЗМЕРЕННО "
                        f"завершился — результат этого прогона не прочитает никто")
    if latest.get("session_pid"):
        return ATTENDED, (f"дерево {tree} объявила сессия `{latest.get('session')}`, её "
                          f"процесс pid{latest.get('session_pid')} жив — прогона ЖДУТ")
    return UNMEASURED, (f"дерево {tree} объявлено сессией `{latest.get('session')}`, но "
                        f"долгоживущего процесса она не назвала — живость не измерима")


def check(target_cwd: str, *, self_pid: int | None = None) -> dict:
    """Return a report dict. ``status`` is one of: clear / collision / unmeasured."""
    target_cwd = os.path.realpath(target_cwd)
    procs = list_pytest_processes(self_pid=self_pid)
    if procs is None:
        return {"status": "unmeasured", "reason": "ps enumeration failed", "target_cwd": target_cwd}

    same_cwd = []
    other_cwd = []
    unresolved = []
    for p in procs:
        p.cwd = resolve_cwd(p.pid)
        if p.cwd is None:
            unresolved.append(p)
        elif os.path.realpath(p.cwd) == target_cwd:
            same_cwd.append(p)
        else:
            other_cwd.append(p)

    owner = _owner_probe()
    entries = None
    log = _announce_log(owner)
    if log is not None:
        try:
            entries, _bad = owner.read_entries(log, None)
        except (OSError, ValueError, TypeError):
            entries = None
    for p in procs:
        p.orphan, p.orphan_why = classify_orphan(p, owner=owner, entries=entries)

    status = "collision" if same_cwd else "clear"
    return {
        "status": status,
        "target_cwd": target_cwd,
        "same_cwd": [vars(p) for p in same_cwd],
        "other_cwd": [vars(p) for p in other_cwd],
        "unresolved": [vars(p) for p in unresolved],
        # Отдельными списками, а не флагом на процессе: читатель, которому нужен
        # ответ «есть ли сироты», не должен фильтровать сам — фильтр на стороне
        # читателя и есть способ, которым находка становится необязательной.
        "orphans": [vars(p) for p in procs if p.orphan == ORPHAN],
        "orphan_unmeasured": [vars(p) for p in procs if p.orphan == UNMEASURED],
    }


def _print_human(report: dict) -> None:
    status = report["status"]
    if status == "unmeasured":
        print(f"⚠️  НЕ ИЗМЕРЕНО: {report['reason']} — считать прогон непроверенным, не чистым.")
        return
    if status == "collision":
        print(f"🛑 СТОЛКНОВЕНИЕ: ещё {len(report['same_cwd'])} pytest в ТОМ ЖЕ дереве ({report['target_cwd']}):")
        for p in report["same_cwd"]:
            print(f"   pid={p['pid']}  start={p['lstart']}  {p['command']}")
        print("   Любой прогон здесь сейчас переписывает data/ вместе с другим — числу верить нельзя.")
        print("   Опознан по lsof -d cwd (командная строка путь дерева не содержит).")
    else:
        print(f"✅ В своём дереве ({report['target_cwd']}) других pytest нет.")

    if report["other_cwd"]:
        print(f"\nℹ️  {len(report['other_cwd'])} pytest в ДРУГИХ деревьях (может замедлить, а может и нет — см. журнал):")
        for p in report["other_cwd"]:
            print(f"   pid={p['pid']}  start={p['lstart']}  cwd={p['cwd']}  {p['command']}")

    if report["unresolved"]:
        print(f"\n⚠️  {len(report['unresolved'])} pytest-процесс(ов) — cwd не разрешён (lsof недоступен для pid):")
        for p in report["unresolved"]:
            print(f"   pid={p['pid']}  start={p['lstart']}  {p['command']}")

    orphans = report.get("orphans") or []
    if orphans:
        print(f"\n🪦 ОСИРОТЕВШИХ ПРОГОНОВ: {len(orphans)} — заказчик мёртв, ядро занято, "
              f"результат не прочитает никто:")
        for p in orphans:
            print(f"   pid={p['pid']}  start={p['lstart']}  cwd={p['cwd']}")
            print(f"      {p['orphan_why']}")
            print(f"      снять: kill -TERM {p['pid']}   (это решение сессии, инструмент не убивает)")

    unmeasured = report.get("orphan_unmeasured") or []
    if unmeasured:
        # Третий исход печатается ВСЛУХ по той же причине, по какой существует:
        # «не измерено» неотличимо от «сирот нет», пока о нём молчат.
        print(f"\n❔ НЕ ИЗМЕРЕНО, кому нужен прогон: {len(unmeasured)} — это НЕ «сирота» "
              f"и НЕ «всё в порядке»:")
        for p in unmeasured:
            print(f"   pid={p['pid']}  cwd={p['cwd']}  — {p['orphan_why']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument("--cwd", default=os.getcwd(), help="tree to check for a collision (default: current dir)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = check(args.cwd, self_pid=os.getpid())

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_human(report)

    if report["status"] == "unmeasured":
        return 2
    if report["status"] == "collision":
        # Столкновение перевешивает сироту: код 1 — про доверие к ТВОЕМУ числу,
        # код 3 — только про машину. Сироты при этом уже напечатаны выше.
        return 1
    if report.get("orphans"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
