#!/usr/bin/env python3
"""
verify_book_series.py — STANDALONE, ZERO-DEPENDENCY verifier for the LANE-A per-book realized series.

A skeptical third party downloads ONLY this file + the public artifact(s)
``data/rates_desk/books/<book_id>/realized_series.jsonl`` and runs:

    python3 verify_book_series.py data/rates_desk/books/

It independently re-derives every ``row_hash`` per docs/PROOF_CHAIN_SPEC.md (§2 canonical-JSON + §5
chain walk, keyed on ``as_of``) and reaches the desk's exact verdict. If a single byte of any published
book row were altered — a forged ``deployable_usd``/carry, a REFUSED book laundered as deployable, a
reordered/back-dated day — the recompute diverges and this tool reports the precise ``broken_at``.

Nothing here imports ``spa_core`` — it follows ONLY the public recipe, reproduced inline. This is the
Lane-A sibling of scripts/verify_spa.py (which owns surfaces A–G); the per-book series is auto-discovered
recursively under any supplied path. stdlib-only · deterministic · fail-CLOSED · NO network.

EXIT CODES
    0  every discovered book chain reproduces byte-for-byte
    1  any mismatch / malformed row / no chains found
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional

# ── PUBLISHED INVARIANTS (verbatim from the per-book series writer; NEVER import them from code) ──
EVENT_TYPE = "rates_desk_book_realized_point"   # fixed for this surface, not stored per-row
GENESIS_PREV = "0" * 64
ENVELOPE_KEYS = ("as_of", "prev_hash", "row_hash")
SERIES_NAME = "realized_series.jsonl"


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def recompute_row_hash(seq: int, row: dict) -> str:
    """SHA-256 over canonical({seq, as_of, event_type, payload, prev_hash}); payload = row − envelope."""
    payload = {k: v for k, v in row.items() if k not in ENVELOPE_KEYS}
    canon = _canonical({
        "seq": seq, "as_of": row.get("as_of"), "event_type": EVENT_TYPE,
        "payload": payload, "prev_hash": row.get("prev_hash"),
    })
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def verify_chain(rows: List[dict]) -> dict:
    """Walk in order; require (1) prev_hash == previous row_hash (genesis '0'*64), (2)
    recompute_row_hash == row_hash. Returns {valid, length, broken_at, head_hash}. fail-CLOSED."""
    expected_prev = GENESIS_PREV
    head = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        try:
            if recompute_row_hash(idx, row) != row.get("row_hash"):
                return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["row_hash"]
        head = row["row_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head}


def _read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            rows.append(json.loads(ln))
    return rows


def _discover(paths: List[str]) -> List[Path]:
    found: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for fp in sorted(p.rglob(SERIES_NAME)):
                if fp.is_file():
                    found.append(fp)
        elif p.is_file() and p.name == SERIES_NAME:
            found.append(p)
    return found


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: verify_book_series.py <dir-or-realized_series.jsonl ...>")
        return 1
    series = _discover(argv)
    if not series:
        print("no realized_series.jsonl files found under the supplied path(s) — nothing to verify")
        return 1
    print("=" * 78)
    print("LANE-A per-book REALIZED SERIES verifier  (zero-dependency · per PROOF_CHAIN_SPEC §2/§5)")
    print("=" * 78)
    ok = True
    for sp in series:
        try:
            rows = _read_jsonl(sp)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  {sp}  : UNREADABLE ({exc})")
            ok = False
            continue
        res = verify_chain(rows)
        bid = sp.parent.name
        print(f"  {bid:>19s}  valid={res['valid']}  len={res['length']}  "
              f"broken_at={res['broken_at']}  head={res['head_hash']}")
        if not res["valid"]:
            ok = False
    print("-" * 78)
    print("VERDICT:", "OK — every book chain reproduces" if ok else "FAIL — a chain diverged")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
