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

2. **Different working trees, concurrent full runs** — NOT always harmful.
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

Exit codes: 0 = clear (no same-cwd collision); 1 = same-cwd collision found
(hazard #1 — treat any prior/concurrent run in this tree as untrustworthy);
2 = could not enumerate processes (fail-CLOSED: treat as "unmeasured", not
"clear").
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class PytestProc:
    pid: int
    lstart: str
    command: str
    cwd: str | None = None


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
    raw = _run(["ps", "-ax", "-o", "pid=,lstart=,command="])
    if raw is None:
        return None
    procs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        rest = parts[1] if len(parts) > 1 else ""
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
        procs.append(PytestProc(pid=pid, lstart=lstart, command=command))
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

    status = "collision" if same_cwd else "clear"
    return {
        "status": status,
        "target_cwd": target_cwd,
        "same_cwd": [vars(p) for p in same_cwd],
        "other_cwd": [vars(p) for p in other_cwd],
        "unresolved": [vars(p) for p in unresolved],
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
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
