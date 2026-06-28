#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.audit.equity_proof_chain — tamper-evident hash-chain over the
EVIDENCED equity / go-live track (F2 honesty fix, 2026-06-28).

Why this exists
===============
The track-record page told reviewers the go-live EQUITY track is verifiable
via ``verify_spa.py`` — but that verifier only re-derives the *rates-desk
decision* chain (``data/rates_desk/decision_log.jsonl`` + ``exit_nav.json`` +
``anchors.jsonl``). The equity series itself had NO chain the verifier could
re-derive: the "verify yourself" command did not actually verify the equity
track. That was honesty-by-conflation.

This module turns the lie into a real differentiator. It builds a deterministic,
single-genesis hash chain over the EVIDENCED equity bars (the only days that
count toward go-live — see ``track_evidence.is_evidenced_bar``) and writes it
as ``data/rates_desk/equity_track.jsonl`` — co-located with the rates-desk
proofs so the SAME one-line command (``python3 verify_spa.py data/rates_desk/``)
now re-derives the equity track too. ``scripts/verify_spa.py`` was extended with
a zero-dependency verifier for exactly this artifact (no ``spa_core`` import on
the reviewer's machine), so the track-record page's claim is now literally TRUE.

Chain recipe (deterministic, documented for independent re-derivation)
======================================================================
* Canonicalization: ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`` → UTF-8 bytes. The SAME canonical-JSON rule the rest of
  the proof chain uses (PROOF_CHAIN_SPEC §2).
* Per-row envelope: ``{seq, date, prev_hash, entry_hash}``. ``payload`` = the
  row's evidence fields (open/close equity, daily yield, apy, source,
  evidenced) — i.e. the row minus the four envelope keys.
* ``entry_hash = sha256(canonical({"seq", "date", "kind", "payload",
  "prev_hash"}))`` with ``kind = EVENT_TYPE`` (a fixed constant, not stored
  per-row — matches the decision-chain recipe shape).
* Genesis ``prev_hash = "0" * 64``; row i's ``prev_hash`` == row i-1's
  ``entry_hash``. So a forged equity number, a reordered/dropped/inserted day,
  or a back-dated edit DIVERGES the recompute and the standalone verifier
  reports the precise ``broken_at``.
* Only EVIDENCED bars (a real ``daily_cycle`` log behind them) are chained, in
  date order. Backfill / warmup / reconstructed bars are NOT in the chain —
  the chain reflects exactly the honest go-live count, nothing padded.

Scope / safety
==============
* Stdlib only. Deterministic. No LLM, no randomness, no network.
* Atomic writes (tmp + os.replace).
* Read-only over ``data/equity_curve_daily.json``; never mutates the track.
* Advisory / measurement: moves no capital, touches no risk/execution.

CLI::

    python3 -m spa_core.audit.equity_proof_chain --build   # write the artifact
    python3 -m spa_core.audit.equity_proof_chain --check   # recompute, print head, write nothing
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

from spa_core.paper_trading.track_evidence import (
    evidenced_bars,
    PAPER_REAL_START,
)

# ── published invariants (must agree with scripts/verify_spa.py) ──────────────
EVENT_TYPE = "equity_track_bar"
GENESIS_PREV = "0" * 64
ENVELOPE_KEYS = ("seq", "date", "prev_hash", "entry_hash")
# The evidence fields that make up each row's payload. Stable, minimal, honest.
PAYLOAD_KEYS = (
    "open_equity",
    "close_equity",
    "daily_yield_usd",
    "apy_today",
    "source",
    "evidenced",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_EQUITY = _REPO_ROOT / "data" / "equity_curve_daily.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "rates_desk" / "equity_track.jsonl"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _row_entry_hash(seq: int, date: str, payload: dict, prev_hash: str) -> str:
    """sha256 over canonical({seq, date, kind, payload, prev_hash}) — see module docstring."""
    canonical = _canonical({
        "seq": seq,
        "date": date,
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


def build_chain(
    equity_path: Path | str | None = None,
    *,
    paper_start=PAPER_REAL_START,
) -> Tuple[List[dict], Optional[str]]:
    """Build the hash-chained list of evidenced-equity rows + return (rows, head_hash).

    Deterministic. Reads ``equity_curve_daily.json`` read-only, filters to the
    evidenced series (date order), and links each bar into a single-genesis
    chain. Empty evidenced series → ([], None) — honest, no fabricated rows.
    """
    path = Path(equity_path) if equity_path is not None else _DEFAULT_EQUITY
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    daily = doc.get("daily") if isinstance(doc, dict) else None
    if not isinstance(daily, list):
        return [], None

    bars = evidenced_bars(daily, paper_start=paper_start)
    # Stable date order (evidenced_bars preserves input order; sort defensively).
    bars = sorted(bars, key=lambda b: str(b.get("date") or ""))

    rows: List[dict] = []
    prev_hash = GENESIS_PREV
    head_hash: Optional[str] = None
    for seq, bar in enumerate(bars):
        date = str(bar.get("date") or "")[:10]
        payload = {
            "open_equity": _num(bar.get("open_equity")),
            "close_equity": _num(bar.get("close_equity", bar.get("equity"))),
            "daily_yield_usd": _num(bar.get("daily_yield_usd")),
            "apy_today": _num(bar.get("apy_today")),
            "source": bar.get("source"),
            "evidenced": bool(bar.get("evidenced", True)),
        }
        entry_hash = _row_entry_hash(seq, date, payload, prev_hash)
        row = {"seq": seq, "date": date, **payload,
               "prev_hash": prev_hash, "entry_hash": entry_hash}
        rows.append(row)
        prev_hash = entry_hash
        head_hash = entry_hash
    return rows, head_hash


def write_chain(
    equity_path: Path | str | None = None,
    out_path: Path | str | None = None,
    *,
    paper_start=PAPER_REAL_START,
) -> dict:
    """Atomically write the equity-track chain as JSONL. Returns a small report."""
    rows, head = build_chain(equity_path, paper_start=paper_start)
    out = Path(out_path) if out_path is not None else _DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(_canonical(r) + "\n" for r in rows)
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp")
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
    return {"rows": len(rows), "head_hash": head, "path": str(out)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.audit.equity_proof_chain",
        description="Tamper-evident hash chain over the EVIDENCED equity/go-live "
                    "track (F2). Co-located with rates-desk proofs so "
                    "`verify_spa.py data/rates_desk/` re-derives it.",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true",
                      help="recompute and atomically write data/rates_desk/equity_track.jsonl")
    mode.add_argument("--check", action="store_true",
                      help="recompute and print the head hash, write NOTHING")
    ap.add_argument("--equity", default=None, help="path to equity_curve_daily.json")
    ap.add_argument("--out", default=None, help="output JSONL path")
    args = ap.parse_args(argv)

    if args.build:
        rep = write_chain(args.equity, args.out)
        print(f"equity_proof_chain: wrote {rep['rows']} evidenced rows → {rep['path']}")
        print(f"equity_proof_chain: head_hash={rep['head_hash']}")
    else:
        rows, head = build_chain(args.equity)
        print(f"equity_proof_chain: {len(rows)} evidenced rows (read-only, nothing written)")
        print(f"equity_proof_chain: head_hash={head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
