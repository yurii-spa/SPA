#!/usr/bin/env python3
"""
scripts/log_session_change.py — the shared multi-session ANNOUNCE log (PROJECT_CONTROL/16).

Parallel Claude sessions record every change here so nobody silently overwrites another's work and
the owner has one place to see "what moved". Append-only JSONL: each call writes ONE line in O_APPEND
mode (< PIPE_BUF ⇒ atomic on POSIX, so concurrent sessions never clobber each other). stdlib-only.

    # record a change:
    python3 scripts/log_session_change.py --summary "fix X" --files a.py b.ts --verified "pytest 66 green"
    # record a change AND say which tracker card it belongs to (step 0b reads this):
    python3 scripts/log_session_change.py --summary "..." --card agent-my-card --files ...
    python3 scripts/log_session_change.py --summary "delivered" --card agent-my-card --card-state done
    # see recent activity (run this at session start):
    python3 scripts/log_session_change.py --tail          # last 20
    python3 scripts/log_session_change.py --tail 50

``--card`` makes the announce↔card link EXPLICIT. Without it the link exists only in free text,
so "is this card already taken?" could only be answered by eye — and on 2026-07-30 that failed:
two sessions took `agent-ci-ignores-golive-gate-tests` an hour apart and did the same work twice
(card `agent-card-claim-collision-guard`). ``scripts/check_card_claim.py`` reads the field
deterministically; ``--card-state done`` releases the claim. Both fields are optional — entries
written without them keep parsing exactly as before.

**The log always lives in the MAIN working tree** (see ``_shared_log``): announcing from an
isolated worktree — which the protocol REQUIRES (§3.4) — used to write into that worktree's own
gitignored ``data/``, so the announcement died with the tree and every reader was blind to it.

**A session's activity is measurable only if the session says which process to look at**
(``durable_process``, card ``agent-durable-session-id``). The ``session`` id defaults to the pid of
this ONE-SHOT CLI process, which is dead the moment the command returns, so ``ps -p`` answered
"no such process" for every entry ever written — including one made a second ago by the session
asking. Steps 0a/0b therefore fell back to the announcement's AGE, and ids that carry no pid at
all (``cycle49``, ``cycle61`` …) were "NOT MEASURED" **for ever**, which on 2026-07-31 locked two
backlog cards out of the queue for 19h+ (card ``agent-weak-mention-locks-card-forever``).
A session that owns a long-lived process — ``scripts/agent_orchestrator.sh`` is one: that shell
waits for the whole cycle — exports ``SPA_SESSION_PID`` (and usually ``SPA_SESSION_ID``), and
every entry then carries ``session_pid`` + ``session_pid_start``, i.e. a process that can actually
be measured. Both keys are only ever ADDED; entries written without them parse exactly as before.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE_LOG = Path(__file__).resolve().parents[1] / "data" / "session_changes.jsonl"
_RESOLVER = Path(__file__).resolve().parent / "check_undelivered_work.py"
_UNSET = object()
_RESOLVER_MOD = _UNSET


def _load_resolver():
    """The sibling module (``check_undelivered_work``) or None — loaded once, never twice.

    It owns ``ps``/``lstart`` parsing and the "where is the shared state" answer; re-implementing
    either here would create the twin that cycle #47 had to hunt down (one copy fixed, the other
    left lying). None (no file / broken import) is a measurement too: callers degrade to the old
    behaviour instead of guessing."""
    global _RESOLVER_MOD
    if _RESOLVER_MOD is _UNSET:
        try:
            spec = importlib.util.spec_from_file_location("_lsc_resolver", _RESOLVER)
            if spec is None or spec.loader is None:
                _RESOLVER_MOD = None
            else:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _RESOLVER_MOD = mod
        except (OSError, ImportError, SyntaxError, AttributeError, ValueError, TypeError):
            _RESOLVER_MOD = None
    return _RESOLVER_MOD


def _shared_log(default: Path) -> Path:
    """The announce log in the MAIN working tree — never in a disposable worktree.

    The protocol REQUIRES autonomous cycles to work in an isolated git worktree (§3.4) and
    ``data/`` is gitignored, so a worktree has no ``data/session_changes.jsonl``: announcing
    from there creates a private one that dies with the tree. Measured 2026-07-31 on orphaned
    cycle #52 — it *did* announce ownership, into
    ``/private/tmp/spa_wt_c52/data/session_changes.jsonl``; the host log never saw it, so both
    step 0a and step 0b were blind to a whole cycle's work (card
    ``agent-claim-without-announce-is-invisible``).

    Resolution lives in ``check_undelivered_work.main_worktree`` — one answer to "where is the
    shared state", not two. Unresolvable (no git, not a repo, tests) → the old path, which is
    correct in the host repo and merely empty elsewhere: readers then say "NOT MEASURED"
    rather than "nothing to report" (fail-CLOSED)."""
    mod = _load_resolver()
    if mod is None:
        return default
    try:
        path, _ = mod.shared_log()
        return Path(path)
    except (OSError, AttributeError, ValueError, TypeError):
        return default


_LOG = _shared_log(_HERE_LOG)


def _session_id() -> str:
    # Stable within a process, distinct across parallel sessions. No secrets.
    return os.environ.get("SPA_SESSION_ID") or f"pid{os.getpid()}"


def durable_process(env=None, ps=None):
    """``({"session_pid": N, "session_pid_start": "<ps lstart>"} , "")`` or ``({}, reason)``.

    The pid comes ONLY from an explicit ``SPA_SESSION_PID`` — never from ``os.getppid()``, and
    that is a deliberate choice, not an omission. The parent of this one-shot command is whatever
    shell happened to run it; for anyone working from a terminal (or a tmux pane) that shell
    outlives the work by days, so a ppid-derived "durable process" would report ACTIVE forever
    and step 0a — whose entire job is to notice work that never reached origin — would go quiet
    about it. That is the fail-OPEN direction (a claim of measurement nobody made, the class of
    #29/#31/#35–#38/#40), so only a session that *declares* its own long-lived process gets one.

    The start time is measured HERE, at write time, and stored verbatim. Without it a later
    reader can only ask "is some process holding this pid?", and a recycled pid would read as a
    live session; with it, "same pid AND same start" is an identity check.

    Returns ``({}, reason)`` — never a half-written pair — whenever the declared pid is not a
    process we can see right now: recording a pid we could not confirm would be exactly the
    plausible-looking number this repo keeps having to delete."""
    env = os.environ if env is None else env
    raw = str(env.get("SPA_SESSION_PID") or "").strip()
    if not raw:
        return {}, "SPA_SESSION_PID не задан — долгоживущего процесса сессия не объявила"
    if not raw.isdigit():
        return {}, f"SPA_SESSION_PID={raw!r} — не число, долгоживущий процесс не записан"
    pid = int(raw)
    if pid <= 1:
        # pid 1 — init/launchd: живёт всегда и не принадлежит сессии ⇒ вечный ложный ACTIVE.
        return {}, f"SPA_SESSION_PID={pid} — это не процесс сессии, долгоживущий процесс не записан"

    mod = _load_resolver()
    probe = ps or (getattr(mod, "_ps_lstart", None) if mod else None)
    if probe is None:
        return {}, "измерить старт процесса нечем (`check_undelivered_work` не загружен)"
    try:
        rc, out = probe(pid)
    except (OSError, ValueError, TypeError) as exc:                     # pragma: no cover
        return {}, f"`ps -p {pid}` не отработал: {exc.__class__.__name__}"
    if rc != 0 or not str(out).strip():
        return {}, (f"процесса pid{pid} сейчас нет (rc={rc}) — объявленный долгоживущий "
                    f"процесс не подтверждён, поле не записано")
    return {"session_pid": pid, "session_pid_start": str(out).strip()}, ""


CARD_STATES = ("claim", "done")


def record(summary: str, files: list, verified: str,
           card: str = "", card_state: str = "", log=None, session: str = "",
           process=None) -> dict:
    """Append ONE announce entry. ``log`` overrides the shared journal (tests, explicit --log);
    ``session`` overrides the writer's own id (a caller announcing on behalf of a session whose
    id it was given — otherwise the entry would carry this process's pid instead); ``process``
    overrides the durable-process probe (tests).

    Kept as the single writer of this schema: ``check_card_claim.claim`` announces through it
    so a claim can never exist without an announcement (card
    ``agent-claim-without-announce-is-invisible``)."""
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": str(session).strip() or _session_id(),
        "summary": summary.strip(),
        "files": [str(f) for f in files],
        "verified": (verified or "").strip(),
    }
    # Optional and only ever ADDED: readers of older entries must keep working unchanged.
    if card:
        entry["card"] = str(card).strip()
        entry["card_state"] = (card_state or "claim").strip()
    proc, _why = durable_process() if process is None else process
    entry.update(proc)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    target = Path(log) if log else _LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    # O_APPEND: atomic for a single sub-PIPE_BUF write → safe under concurrent sessions.
    with open(target, "a", encoding="utf-8") as fh:
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
    ap.add_argument("--card", default="", help="tracker card this work belongs to (id or path)")
    ap.add_argument("--card-state", default="claim", choices=CARD_STATES,
                    help="claim = taking/holding the card (default); done = claim released")
    ap.add_argument("--tail", nargs="?", type=int, const=20, help="print the last N entries (default 20)")
    args = ap.parse_args(argv)

    if args.tail is not None:
        rows = tail(args.tail)
        if not rows:
            print("(no session changes recorded yet)")
            return 0
        for r in rows:
            files = ", ".join(Path(f).name for f in r.get("files", [])) or "-"
            card = r.get("card")
            print(f"{r.get('ts')}  [{r.get('session')}]  {r.get('summary')}")
            if card:
                print(f"    card: {card} ({r.get('card_state') or 'claim'})")
            print(f"    files: {files}   verified: {r.get('verified') or '-'}")
        return 0

    if not args.summary:
        ap.error("provide --summary (and --files/--verified), or --tail to read")
    proc, why = durable_process()
    e = record(args.summary, args.files, args.verified, args.card, args.card_state,
               process=(proc, why))
    card = f" card={e['card']}({e['card_state']})" if e.get("card") else ""
    print(f"announced: {e['ts']} [{e['session']}]{card} {e['summary']}")
    if proc:
        print(f"    долгоживущий процесс: pid{proc['session_pid']} "
              f"(старт {proc['session_pid_start']}) — активность сессии измерима")
    elif os.environ.get("SPA_SESSION_PID"):
        # Заявлен, но не подтверждён — молчать нельзя: сессия думает, что её видно.
        print(f"    ⚠️  долгоживущий процесс НЕ записан: {why}", file=sys.stderr)
    else:
        # Не заявлен вовсе. Раньше об этом молчали, и обе цены платились уже после —
        # чужими циклами: (1) шаги 0a/0b печатали «активность не измерена» о сессии,
        # которая просто не сказала, на какой процесс смотреть; (2) следующая команда той
        # же сессии объявлялась под ДРУГИМ ярлыком (pid однократной команды), и сессия
        # начинала отказывать сама себе — вплоть до «снять чужой захват можно только с
        # --force» на СВОЁМ захвате (карточка `agent-self-claim-blocked-by-own-second-identity`,
        # цикл #70). Опознание по якорю это чинит постфактум, но якорю неоткуда взяться,
        # если процесс не объявлен, — поэтому предупреждение, а не тишина.
        # stderr и код возврата 0: это подсказка, а не отказ.
        print(f"    ⚠️  сессия не объявила долгоживущий процесс: ярлык `{e['session']}` — pid "
              f"ОДНОКРАТНОЙ команды, он умрёт вместе с ней, а следующая команда объявится под "
              f"другим ярлыком. Перед первым объявлением: "
              f"export SPA_SESSION_ID=<имя> SPA_SESSION_PID=<pid долгоживущего процесса>",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
