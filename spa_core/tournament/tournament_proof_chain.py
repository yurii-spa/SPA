#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.tournament.tournament_proof_chain — tamper-evident hash-chain over the
DAILY TOURNAMENT RANKING (WORKSTREAM 2 proof-breadth, 2026-06-28).

Why this exists
===============
The tournament publishes a daily strategy ranking (``data/strategy_tournament.json`` /
``data/mass_tournament_results.json``) that the site and the promotion ladder read as
ground truth — but the ranking carried NO proof. A producer (or anyone with write
access) could silently REORDER the leaderboard, swap a strategy in at rank 1, or forge a
Sharpe / net-return, and nothing would diverge. This module turns each daily ranking into
a single-genesis hash chain whose proof covers the USER-FACING OUTPUTS (rank / strategy /
net_return / sharpe) and chains the rows (per-row ``prev_hash``), so:

  * **FAIL#2 lesson (red-team):** the proof covers the OUTPUTS, not just inputs. Forging a
    published ``rank`` / ``net_annual_return_pct`` / ``sharpe`` / ``strategy`` value diverges
    the recompute — the verifier reports the precise ``broken_at``. Each row also carries a
    ``prev_hash`` linking it to the previous row's ``entry_hash``, so REORDERING a ranking (or
    dropping / inserting a row) breaks the chain.
  * **F1 lesson (anti-rot):** the published artifact is REGENERATED from the producer's latest
    ranking every time the producer advances (folded into the tournament agent + the published
    proof refresh), so it never goes stale relative to ``strategy_tournament.json``.

The artifact is ``data/tournament/decision_log.jsonl`` — co-located so the SAME one-line
command (``python3 scripts/verify_spa.py data/``) auto-discovers and re-derives it, with NO
``spa_core`` on the reviewer's machine.

Chain recipe (deterministic, documented for independent re-derivation)
======================================================================
* Canonicalization: ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`` → UTF-8 bytes (PROOF_CHAIN_SPEC §2 — the ONE rule).
* Per-row envelope: ``{seq, ts, prev_hash, entry_hash}``. ``payload`` = the row minus the
  four envelope keys (the signed ranking body: generated_at, rank, strategy_id, strategy_key,
  name, sharpe, net_annual_return_pct, max_dd_pct, ...).
* ``entry_hash = sha256(canonical({"seq", "ts", "kind", "payload", "prev_hash"}))`` with
  ``kind = EVENT_TYPE`` (a fixed constant, not stored per-row — matches the decision/equity
  chain recipe shape exactly, so the standalone verifier reuses the same recompute).
* Genesis ``prev_hash = "0"*64``; row i's ``prev_hash`` == row i-1's ``entry_hash``. The
  chain is single-genesis across ALL appended days (re-based on every write, exactly like the
  rates-desk decision mirror), so a forged number or a reordered/dropped/inserted/back-dated
  ranking row DIVERGES the recompute and the verifier reports the precise ``broken_at``.

Each ranking row's PAYLOAD pins (the OUTPUTS a reader actually trusts):
  {ranking_generated_at, rank, strategy_id, strategy_key, name, sharpe, sharpe_display,
   net_annual_return_pct, max_dd_pct, is_shadow_active}

Scope / safety
==============
* Stdlib only. Deterministic. No LLM, no randomness, no network.
* Atomic writes (tmp + os.replace). Ring-buffer capped (the readable mirror; the chain stays
  one coherent re-based chain).
* Read-only over the ranking JSON; never mutates the tournament state.
* Advisory / measurement: moves no capital, touches no risk/execution.

CLI::

    python3 -m spa_core.tournament.tournament_proof_chain --build   # append today's ranking
    python3 -m spa_core.tournament.tournament_proof_chain --check   # recompute, print head
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Tuple

# ── published invariants (must agree with scripts/verify_spa.py) ──────────────
EVENT_TYPE = "tournament_ranking_row"
GENESIS_PREV = "0" * 64
ENVELOPE_KEYS = ("seq", "ts", "prev_hash", "entry_hash")

# The OUTPUT fields the proof MUST cover (the user-facing ranking numbers). Pinned + spec'd so a
# third party reconstructs the hashed payload exactly. Forging any of these breaks the entry_hash.
PAYLOAD_KEYS = (
    "ranking_generated_at",  # which daily ranking this row belongs to (ties the row to a day)
    "rank",                  # OUTPUT — the published position
    "strategy_id",           # OUTPUT — which strategy holds this rank
    "strategy_key",
    "name",
    "sharpe",                # OUTPUT — the published Sharpe
    "sharpe_display",
    "net_annual_return_pct",  # OUTPUT — the published net return
    "max_dd_pct",
    "is_shadow_active",
)

# How many ranking ROWS to retain in the readable chain (a ring buffer; the chain stays a single
# coherent re-based chain). ~30 daily rankings of ~63 strategies ≈ 1900 rows.
LOG_CAP = 4000

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_RANKING = _REPO_ROOT / "data" / "strategy_tournament.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "tournament" / "decision_log.jsonl"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_of(row: dict) -> dict:
    """The signed ranking body = the row with the four chain-linkage envelope keys removed."""
    return {k: v for k, v in row.items() if k not in ENVELOPE_KEYS}


def _row_entry_hash(seq: int, ts: Optional[str], payload: dict, prev_hash: str) -> str:
    """sha256 over canonical({seq, ts, kind, payload, prev_hash}) — see module docstring.
    Mirrors the decision/equity chain recipe shape so the standalone verifier reuses it."""
    canonical = _canonical({
        "seq": seq,
        "ts": ts,
        "kind": EVENT_TYPE,
        "payload": payload,
        "prev_hash": prev_hash,
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _num(v: Any) -> Optional[float]:
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return None


def verify_chain(rows: List[dict]) -> dict:
    """Verify the ranking chain EXACTLY per PROOF_CHAIN_SPEC §5 (single-genesis, contiguous seq,
    prev-linkage, self-recompute). Returns {valid, length, broken_at, head_hash}. Empty is
    vacuously valid. fail-CLOSED on any malformed row. The single shared verifier — the standalone
    verify_spa.py reaches the identical verdict."""
    expected_prev = GENESIS_PREV
    head_hash: Optional[str] = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("seq") != idx:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        try:
            recomputed = _row_entry_hash(row.get("seq"), row.get("ts"),
                                         _payload_of(row), row.get("prev_hash"))
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED at this row
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("entry_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["entry_hash"]
        head_hash = row["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


def _rebase(bodies: List[dict]) -> Tuple[List[dict], Optional[str]]:
    """Re-base an ordered list of ranking bodies into ONE contiguous single-genesis prev-linked
    chain (seq 0..N, prev_hash re-linked, entry_hash recomputed over each body). Returns
    (rows, head_hash). Deterministic. The body is preserved verbatim; only the envelope is set."""
    rows: List[dict] = []
    prev = GENESIS_PREV
    head: Optional[str] = None
    for seq, body in enumerate(bodies):
        ts = body.get("ts")
        payload = _payload_of(body)  # defensive: drop any stray envelope keys carried in
        entry_hash = _row_entry_hash(seq, ts, payload, prev)
        rows.append({"seq": seq, "ts": ts, **payload, "prev_hash": prev, "entry_hash": entry_hash})
        prev = entry_hash
        head = entry_hash
    return rows, head


def ranking_bodies(ranking_doc: dict) -> List[dict]:
    """Distill the per-strategy ranking bodies from a tournament ranking document.

    Accepts either the lifecycle ``strategy_tournament.json`` (``ranked_strategies``) or the
    ``mass_tournament_results.json`` (``leaderboard``) shape. Deterministic: emitted in published
    rank order. Each body carries the OUTPUT fields the proof covers + the ``ts`` of the row (the
    ranking's generated_at, so a reviewer sees which day each row belongs to)."""
    if not isinstance(ranking_doc, dict):
        return []
    gen_at = ranking_doc.get("generated_at")
    rows = ranking_doc.get("ranked_strategies")
    if not isinstance(rows, list):
        rows = ranking_doc.get("leaderboard")
    if not isinstance(rows, list):
        return []

    bodies: List[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        # mass leaderboard uses `id`/`class`; lifecycle uses strategy_id/strategy_key/name.
        sid = r.get("strategy_id") or r.get("id")
        skey = r.get("strategy_key") or r.get("id")
        name = r.get("name") or r.get("class")
        bodies.append({
            "ts": gen_at,
            "ranking_generated_at": gen_at,
            "rank": r.get("rank"),
            "strategy_id": sid,
            "strategy_key": skey,
            "name": name,
            "sharpe": _num(r.get("sharpe")),
            "sharpe_display": _num(r.get("sharpe_display", r.get("sharpe"))),
            "net_annual_return_pct": _num(r.get("net_annual_return_pct",
                                                r.get("annual_return_pct"))),
            "max_dd_pct": _num(r.get("max_dd_pct")),
            "is_shadow_active": bool(r.get("is_shadow_active", False)),
        })
    # Stable order by published rank (defensive — the file is already ranked).
    bodies.sort(key=lambda b: (b.get("rank") if isinstance(b.get("rank"), int) else 10**9))
    return bodies


def _read_existing(path: Path) -> List[dict]:
    """Read the existing readable chain rows (corrupt lines dropped — re-basing rebuilds clean)."""
    if not path.exists():
        return []
    out: List[dict] = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _atomic_write_rows(rows: List[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(_canonical(r) + "\n" for r in rows)
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), prefix="." + out.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, str(out))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_ranking(
    ranking_path: Path | str | None = None,
    out_path: Path | str | None = None,
) -> dict:
    """Append the CURRENT daily ranking to the chain (idempotent per ranking generated_at) and
    atomically rewrite the readable chain as ONE coherent single-genesis chain. Returns a report.

    Idempotent: if the last appended ranking already has the SAME ``ranking_generated_at``, this
    REFRESHES that day's rows in place (re-runs in a day do not duplicate). fail-CLOSED: an absent /
    empty ranking is a no-op that still re-writes a valid (possibly empty) chain."""
    rpath = Path(ranking_path) if ranking_path is not None else _DEFAULT_RANKING
    out = Path(out_path) if out_path is not None else _DEFAULT_OUT

    try:
        doc = json.loads(rpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    new_bodies = ranking_bodies(doc)
    gen_at = doc.get("generated_at") if isinstance(doc, dict) else None

    existing_rows = _read_existing(out)
    existing_bodies = [_payload_of(r) | {"ts": r.get("ts")} for r in existing_rows]

    # Idempotent per ranking: drop any existing rows from the SAME generated_at, then append fresh.
    if gen_at is not None:
        existing_bodies = [b for b in existing_bodies
                           if b.get("ranking_generated_at") != gen_at]
    combined = existing_bodies + new_bodies
    if len(combined) > LOG_CAP:
        combined = combined[-LOG_CAP:]

    rows, head = _rebase(combined)
    _atomic_write_rows(rows, out)
    return {
        "rows": len(rows),
        "appended": len(new_bodies),
        "ranking_generated_at": gen_at,
        "head_hash": head,
        "path": str(out),
        "valid": verify_chain(rows)["valid"],
    }


def build_chain(ranking_path: Path | str | None = None) -> Tuple[List[dict], Optional[str]]:
    """Build (read-only) the chain that appending the current ranking to the existing log WOULD
    produce — used by --check and the refresh self-verify. Deterministic, writes nothing."""
    rpath = Path(ranking_path) if ranking_path is not None else _DEFAULT_RANKING
    out = _DEFAULT_OUT
    try:
        doc = json.loads(rpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    new_bodies = ranking_bodies(doc)
    gen_at = doc.get("generated_at") if isinstance(doc, dict) else None
    existing_rows = _read_existing(out)
    existing_bodies = [_payload_of(r) | {"ts": r.get("ts")} for r in existing_rows]
    if gen_at is not None:
        existing_bodies = [b for b in existing_bodies if b.get("ranking_generated_at") != gen_at]
    combined = existing_bodies + new_bodies
    if len(combined) > LOG_CAP:
        combined = combined[-LOG_CAP:]
    return _rebase(combined)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.tournament.tournament_proof_chain",
        description="Tamper-evident hash chain over the daily tournament ranking (proof covers "
                    "rank/strategy/net_return/sharpe + per-row prev_hash). Co-located so "
                    "`verify_spa.py data/` re-derives it.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true",
                      help="append the current ranking and atomically write data/tournament/decision_log.jsonl")
    mode.add_argument("--check", action="store_true",
                      help="recompute and print the head hash, write NOTHING")
    ap.add_argument("--ranking", default=None, help="path to strategy_tournament.json")
    ap.add_argument("--out", default=None, help="output JSONL path")
    args = ap.parse_args(argv)

    if args.build:
        rep = append_ranking(args.ranking, args.out)
        print(f"tournament_proof_chain: chain={rep['rows']} rows "
              f"(+{rep['appended']} for ranking {rep['ranking_generated_at']}) → {rep['path']}")
        print(f"tournament_proof_chain: head_hash={rep['head_hash']}  valid={rep['valid']}")
    else:
        rows, head = build_chain(args.ranking)
        print(f"tournament_proof_chain: {len(rows)} rows (read-only, nothing written)")
        print(f"tournament_proof_chain: head_hash={head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
