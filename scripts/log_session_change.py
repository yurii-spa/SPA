#!/usr/bin/env python3
"""
scripts/log_session_change.py — the shared multi-session ANNOUNCE log (PROJECT_CONTROL/16).

Parallel Claude sessions record every change here so nobody silently overwrites another's work and
the owner has one place to see "what moved". Append-only JSONL: each call writes ONE line in O_APPEND
mode (< PIPE_BUF ⇒ atomic on POSIX, so concurrent sessions never clobber each other). stdlib-only.

    # record a change:
    python3 scripts/log_session_change.py --summary "fix X" --files a.py b.ts --verified "pytest 66 green"
    # see recent activity (run this at session start):
    python3 scripts/log_session_change.py --tail          # last 20
    python3 scripts/log_session_change.py --tail 50
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_LOG = Path(__file__).resolve().parents[1] / "data" / "session_changes.jsonl"


def _session_id() -> str:
    # Stable within a process, distinct across parallel sessions. No secrets.
    return os.environ.get("SPA_SESSION_ID") or f"pid{os.getpid()}"


def record(summary: str, files: list, verified: str) -> dict:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": _session_id(),
        "summary": summary.strip(),
        "files": [str(f) for f in files],
        "verified": (verified or "").strip(),
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    # O_APPEND: atomic for a single sub-PIPE_BUF write → safe under concurrent sessions.
    with open(_LOG, "a", encoding="utf-8") as fh:
        fh.write(line)
    return entry


def tail(n: int) -> list:
    if not _LOG.exists():
        return []
    lines = _LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Shared multi-session change-announce log.")
    ap.add_argument("--summary", help="one-line description of the change + why")
    ap.add_argument("--files", nargs="*", default=[], help="absolute paths changed")
    ap.add_argument("--verified", default="", help="how it was verified (tests/build exit codes)")
    ap.add_argument("--tail", nargs="?", type=int, const=20, help="print the last N entries (default 20)")
    args = ap.parse_args(argv)

    if args.tail is not None:
        rows = tail(args.tail)
        if not rows:
            print("(no session changes recorded yet)")
            return 0
        for r in rows:
            files = ", ".join(Path(f).name for f in r.get("files", [])) or "-"
            print(f"{r.get('ts')}  [{r.get('session')}]  {r.get('summary')}")
            print(f"    files: {files}   verified: {r.get('verified') or '-'}")
        return 0

    if not args.summary:
        ap.error("provide --summary (and --files/--verified), or --tail to read")
    e = record(args.summary, args.files, args.verified)
    print(f"announced: {e['ts']} [{e['session']}] {e['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
