#!/usr/bin/env python3
"""Подсчёт карточек трекера — с ОБЯЗАТЕЛЬНЫМ указанием источника (ADR-152).

Зачем отдельный инструмент вместо `grep | wc -l`. 27.08 владелец попросил замерить,
движется ли бэклог. Замер был снят с ЛОКАЛЬНОГО дерева и показал 525 карточек, из них
237 `done`. На origin в тот же момент было 719 и 379. Разница в 142 карточки — не работа
за день, а накопленный разрыв копий: `nimbalyst-local/` не синхронизируется с origin
НИКОГДА (пишется локально, merge затёр бы незапушенное).

Вечерний замер сняли уже с origin — и сравнивать его с утренним стало нельзя. Ответа на
простой вопрос «сдвинулся ли бэклог» не получилось вовсе.

Хуже всего, что ADR-152 про ровно эту слепоту был написан ЗА НЕСКОЛЬКО ЧАСОВ ДО ЭТОГО, тем
же автором. Значит правило, которое надо помнить, не работает — работает только проверка,
которая называет свой источник сама.

Поэтому здесь нет режима «просто посчитать»: любой вывод несёт имя источника и, для
локального дерева, отставание индекса.

Использование:
    python3 scripts/tracker_counts.py              # origin (истина)
    python3 scripts/tracker_counts.py --local      # локальное дерево, с предупреждением
    python3 scripts/tracker_counts.py --at <ISO>   # состояние origin на момент времени
    python3 scripts/tracker_counts.py --json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER = "nimbalyst-local/tracker"
_STATUS = re.compile(r"^status:\s*(\S+)", re.M)


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    return r.stdout.strip() if r.returncode == 0 else ""


def _status_of(text: str) -> str:
    m = _STATUS.search(text)
    return m.group(1) if m else "нет-статуса"


def counts_local() -> tuple[collections.Counter, dict]:
    c, ids = collections.Counter(), collections.defaultdict(list)
    base = os.path.join(ROOT, TRACKER)
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if not name.endswith(".md") or name.startswith("_"):
            continue
        with open(os.path.join(base, name), encoding="utf-8", errors="ignore") as fh:
            st = _status_of(fh.read())
        c[st] += 1
        ids[st].append(name[:-3])
    return c, ids


def counts_ref(ref: str) -> tuple[collections.Counter, dict]:
    files = _git("ls-tree", "-r", "--name-only", ref, TRACKER + "/").split()
    c, ids = collections.Counter(), collections.defaultdict(list)
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if not name.endswith(".md") or name.startswith("_"):
            continue
        st = _status_of(_git("show", f"{ref}:{f}"))
        c[st] += 1
        ids[st].append(name[:-3])
    return c, ids


def source_note(local: bool) -> str:
    """Строка источника. Для локального дерева ОБЯЗАНА назвать отставание."""
    if not local:
        return f"origin/main @ {_git('rev-parse', '--short', 'origin/main') or '?'}"
    behind = _git("rev-list", "--count", "HEAD..origin/main")
    if not behind:
        return ("ЛОКАЛЬНОЕ дерево · отставание НЕ ИЗМЕРЕНО — "
                "числа могут не отражать origin")
    return (f"ЛОКАЛЬНОЕ дерево · отстаёт от origin на {behind} коммит(ов) — "
            f"nimbalyst-local/ НЕ синхронизируется, числа НЕ отражают origin")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="считать локальное дерево")
    ap.add_argument("--at", help="состояние origin на момент (ISO)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.at:
        ref = _git("rev-list", "-1", f"--before={a.at}", "origin/main")
        if not ref:
            print(f"нет коммита origin/main до {a.at}", file=sys.stderr)
            return 1
        c, ids = counts_ref(ref)
        src = f"origin/main @ {ref[:9]} (на {a.at})"
    elif a.local:
        c, ids = counts_local()
        src = source_note(local=True)
    else:
        c, ids = counts_ref("origin/main")
        src = source_note(local=False)

    if a.json:
        print(json.dumps({"source": src, "counts": dict(c), "ids": dict(ids)},
                         ensure_ascii=False, indent=1))
        return 0

    print(f"  ИСТОЧНИК: {src}\n")
    for st, n in c.most_common():
        print(f"   {st:16s} {n:4d}")
    print(f"\n   ВСЕГО            {sum(c.values()):4d}")
    print(f"   ОЧЕРЕДЬ          {c.get('new', 0) + c.get('backlog', 0):4d}  (new + backlog)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
