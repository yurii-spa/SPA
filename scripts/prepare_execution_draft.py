#!/usr/bin/env python3
"""
scripts/prepare_execution_draft.py — CLI for the E1 level-A draft-prep layer.

Reads a de-risking *recommendation* (JSON from a file arg or stdin) and prints an
UNSIGNED, human-reviewable draft transaction. It NEVER signs, sends, or moves funds —
it only prepares calldata for a human to sign in their OWN wallet (non-custodial).

Usage:
    echo '{"kind":"revoke_approval","token":"0x..","spender":"0x..",
           "evidence_level":"L2","tail":"a malicious spender can drain the balance"}' \
        | python3 scripts/prepare_execution_draft.py

    python3 scripts/prepare_execution_draft.py path/to/recommendation.json [--json]

Exit code: 0 if a signable draft was produced, 2 if the recommendation was REFUSED
(fail-closed) or malformed — so a caller/agent can gate on it.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.execution.draft_prep import prepare_draft  # noqa: E402


def _load(argv: list) -> dict:
    args = [a for a in argv[1:] if not a.startswith("--")]
    raw = open(args[0], encoding="utf-8").read() if args else sys.stdin.read()
    return json.loads(raw)


def main(argv: list) -> int:
    want_json = "--json" in argv
    try:
        rec = _load(argv)
    except (OSError, ValueError) as e:
        print(f"ERROR: could not read/parse recommendation JSON: {e}", file=sys.stderr)
        return 2

    draft = prepare_draft(rec)

    if want_json:
        print(json.dumps(draft.to_dict(), indent=2))
        return 2 if draft.refused else 0

    print("=" * 74)
    if draft.refused:
        print(f"REFUSED ({draft.kind}): {draft.reason}")
        print("  → fail-closed: nothing prepared. Fix the recommendation and retry.")
        print("=" * 74)
        return 2

    print(f"DRAFT — {draft.kind}  (evidence {draft.evidence_level})")
    print("-" * 74)
    print(draft.action_summary)
    print()
    print(f"  tail        : {draft.tail}")
    print(f"  {draft.refusal_note}")
    print()
    if draft.unsigned_tx:
        tx = draft.unsigned_tx
        print("  UNSIGNED TX (you sign this in YOUR OWN wallet):")
        print(f"    to      : {tx['to']}")
        print(f"    value   : {tx['value']}")
        print(f"    chainId : {tx['chainId']}")
        print(f"    data    : {tx['data']}")
    else:
        print("  (review-only — exact calldata must be built via the Safe proposal path)")
    print()
    print(f"  signed={draft.signed}  requires_human_signature={draft.requires_human_signature}"
          f"  exec_armed={draft.exec_armed}")
    print(f"  {draft.notice}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
