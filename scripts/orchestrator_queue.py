#!/usr/bin/env python3
"""CLI over the files-first owner-queue (ENV_SETUP_BRIEF_v3 · Этап 3).

Deterministic, stdlib-only. Used by the orchestrator protocol (docs/ORCHESTRATOR_PROTOCOL.md)
to scan Owner-Done / Inbox cards, move card status, and notify the owner via Telegram.

Examples::

    # list owner-decision cards the owner has answered (needs ingest):
    python3 scripts/orchestrator_queue.py list --type owner-decision --status owner-done --json

    # list new inbox tasks:
    python3 scripts/orchestrator_queue.py list --type inbox --json

    # after ingesting an owner decision, move it to ingested (owner-done is FORBIDDEN):
    python3 scripts/orchestrator_queue.py set-status nimbalyst-local/tracker/own-08-spa-naming.md ingested

    # Telegram-notify a freshly created needs-owner card (§3.3):
    python3 scripts/orchestrator_queue.py notify nimbalyst-local/tracker/own-99-foo.md
    python3 scripts/orchestrator_queue.py notify <path> --check   # build message, do not send
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Ensure repo root is on sys.path (works when run from scripts/ or repo root).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.owner_queue.queue import (
    OwnerDoneForbidden,
    create_card,
    ingest_notes,
    scan_promotions,
    first_instruction_line,
    list_cards,
    set_status,
)
from spa_core.owner_queue.notify import notify_needs_owner


def _card_dict(c) -> dict:
    return {
        "id": c.id,
        "path": str(c.path),
        "type": c.tracker_type,
        "status": c.status,
        "priority": c.priority,
        "title": c.title,
        "owner": c.owner,
        "legacy_id": c.legacy_id,
        "first_instruction": first_instruction_line(c),
    }


def cmd_list(args) -> int:
    cards = list_cards(tracker_type=args.type, status=args.status)
    if args.json:
        print(json.dumps([_card_dict(c) for c in cards], ensure_ascii=False, indent=2))
    else:
        if not cards:
            print("(no matching cards)")
        for c in cards:
            print(f"[{c.status:<11}] {c.tracker_type:<14} {c.id}  —  {c.title}")
    return 0


def cmd_set_status(args) -> int:
    try:
        set_status(args.path, args.status)
    except OwnerDoneForbidden as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {args.path} -> status: {args.status}")
    return 0


def cmd_create(args) -> int:
    body = args.body or ""
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    extra = {}
    for kv in args.field or []:
        k, _, v = kv.partition("=")
        if k:
            extra[k.strip()] = v.strip()
    try:
        path = create_card(
            args.type, args.title, body,
            status=args.status, source=args.source, extra_fields=extra or None,
        )
    except OwnerDoneForbidden as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(str(path))
    return 0


def cmd_ingest_notes(args) -> int:
    created = ingest_notes(notes_dir=args.dir)
    if not created:
        print("(no loose notes to ingest)")
    for p in created:
        print(f"ingested -> {p}")
    return 0


def cmd_promotions(args) -> int:
    proms = scan_promotions()
    if args.json:
        print(json.dumps([{"path": str(p.path), "title": p.title, "snippet": p.snippet} for p in proms],
                         ensure_ascii=False, indent=2))
    else:
        if not proms:
            print("(no #promote tags found in docs/ideas/ or docs/rules-draft/)")
        for p in proms:
            print(f"#promote  {p.path}  —  {p.title}")
    return 0


def cmd_notify(args) -> int:
    msg = notify_needs_owner(args.path, dry_run=args.check)
    if args.check:
        print(msg)
    else:
        print(f"OK: notified for {args.path}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Owner-queue CLI (files-first tracker cards)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list cards, optionally filtered")
    pl.add_argument("--type", default=None, help="trackerStatus.type (owner-decision|inbox)")
    pl.add_argument("--status", default=None, help="status filter (needs-owner|owner-done|ingested|...)")
    pl.add_argument("--json", action="store_true", help="JSON output")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("set-status", help="atomically set a card's status (owner-done FORBIDDEN)")
    ps.add_argument("path")
    ps.add_argument("status")
    ps.set_defaults(func=cmd_set_status)

    pc = sub.add_parser("create", help="create a new card (used by Telegram/Obsidian intake)")
    pc.add_argument("--type", required=True, help="tracker type (inbox|owner-decision)")
    pc.add_argument("--title", required=True)
    pc.add_argument("--body", default=None)
    pc.add_argument("--body-file", default=None)
    pc.add_argument("--status", default=None)
    pc.add_argument("--source", default=None, help="nimbalyst|obsidian|telegram|voice")
    pc.add_argument("--field", action="append", help="extra frontmatter k=v (repeatable)")
    pc.set_defaults(func=cmd_create)

    pi = sub.add_parser("ingest-notes", help="convert loose Obsidian inbox/ notes → Inbox cards")
    pi.add_argument("--dir", default=None, help="notes dir (default: repo inbox/)")
    pi.set_defaults(func=cmd_ingest_notes)

    pp = sub.add_parser("promotions", help="list #promote-tagged ideas/rules-draft (Этап 7.3)")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_promotions)

    pn = sub.add_parser("notify", help="Telegram-notify a needs-owner card (§3.3)")
    pn.add_argument("path")
    pn.add_argument("--check", action="store_true", help="build message, do not send")
    pn.set_defaults(func=cmd_notify)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
