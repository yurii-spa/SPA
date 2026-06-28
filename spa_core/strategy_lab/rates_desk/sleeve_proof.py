#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.strategy_lab.rates_desk.sleeve_proof — tamper-evident proof chain over the
SLEEVE FORWARD PAPER SERIES (WORKSTREAM 2 proof-breadth, 2026-06-28).

Why this exists
===============
The rates-desk paper sleeves persist a growing forward time-series — one point per UTC day —
to ``data/rates_desk/paper/<sleeve>_series.json`` (e.g. ``rates_desk_fixed_carry_series.json``).
The PROMOTION LADDER (sleeve → live-paper → fundable) is built on this track. But the series
points carried NO proof: a producer could silently inflate ``equity_usd`` / ``net_apy_pct`` on a
historical day, drop a flat day, or reorder the track, and the promotion decision would rest on
tampered data. This module chains each sleeve series into a single-genesis hash chain whose proof
covers the USER-FACING OUTPUTS (the forward equity / yield / book counts) and chains the rows.

  * **FAIL#2 lesson (red-team):** the proof covers the OUTPUTS (``equity_usd`` / ``net_apy_pct`` /
    ``open_books`` / ``closed_books`` / ``approvals`` / ``refusals``), not just the date. Forging a
    published forward number diverges the recompute. Every row carries a ``prev_hash`` linking it to
    the previous row's ``entry_hash`` (genesis ``"0"*64``), so REORDERING / dropping / inserting /
    back-dating a forward point breaks the chain — the verifier reports the precise ``broken_at``.
  * **F1 lesson (anti-rot):** the published proof artifacts are REGENERATED from the producer's
    latest series whenever the sleeve ticks (folded into the rates-desk paper agent + the published
    proof refresh), so they never go stale relative to the ``*_series.json`` files.

Artifacts are ``data/rates_desk/paper/<sleeve>_series_proof.jsonl`` — co-located so the SAME
one-line command (``python3 scripts/verify_spa.py data/``) auto-discovers and re-derives EVERY
sleeve proof, with NO ``spa_core`` on the reviewer's machine.

Chain recipe (deterministic, documented for independent re-derivation)
======================================================================
* Canonicalization: ``json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
  → UTF-8 bytes (PROOF_CHAIN_SPEC §2 — the ONE rule).
* Per-row envelope: ``{seq, date, prev_hash, entry_hash}``. ``payload`` = the row minus the four
  envelope keys (sleeve_id + the OUTPUT forward numbers).
* ``entry_hash = sha256(canonical({"seq", "date", "kind", "payload", "prev_hash"}))`` with
  ``kind = EVENT_TYPE`` (a fixed constant, not stored per-row — matches the equity-track recipe
  shape exactly, so the standalone verifier reuses the same recompute).
* Genesis ``prev_hash = "0"*64``; row i's ``prev_hash`` == row i-1's ``entry_hash``.

Each forward point's PAYLOAD pins:
  {sleeve_id, ts, equity_usd, net_apy_pct, open_books, closed_books, approvals, refusals}

Scope / safety
==============
* Stdlib only. Deterministic. No LLM, no randomness, no network.
* Atomic writes (tmp + os.replace). Read-only over the ``*_series.json`` files — never mutates them.
* Advisory / RESEARCH only: moves no capital, touches no risk/execution, no go-live track.

CLI::

    python3 -m spa_core.strategy_lab.rates_desk.sleeve_proof --build   # write all sleeve proofs
    python3 -m spa_core.strategy_lab.rates_desk.sleeve_proof --check   # recompute, print heads
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── published invariants (must agree with scripts/verify_spa.py) ──────────────
EVENT_TYPE = "sleeve_forward_point"
GENESIS_PREV = "0" * 64
ENVELOPE_KEYS = ("seq", "date", "prev_hash", "entry_hash")
# The OUTPUT forward fields the proof MUST cover (the promotion-ladder numbers).
PAYLOAD_KEYS = (
    "sleeve_id",
    "ts",
    "equity_usd",       # OUTPUT — the forward equity the ladder reads
    "net_apy_pct",      # OUTPUT — the forward yield
    "open_books",
    "closed_books",
    "approvals",
    "refusals",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAPER_DIR = _REPO_ROOT / "data" / "rates_desk" / "paper"
# A sleeve series file matches "*_series.json"; its proof is "*_series_proof.jsonl" alongside it.
_SERIES_SUFFIX = "_series.json"
_PROOF_SUFFIX = "_series_proof.jsonl"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_of(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ENVELOPE_KEYS}


def _row_entry_hash(seq: int, date: str, payload: dict, prev_hash: str) -> str:
    """sha256 over canonical({seq, date, kind, payload, prev_hash}) — mirrors the equity-track recipe."""
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
        return round(float(v), 8)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def point_payload(sleeve_id: str, pt: dict) -> dict:
    """Distill ONE forward point's signed payload (the OUTPUT numbers). Deterministic. Drops any
    non-OUTPUT diagnostic noise (e.g. scan_diag) so the proof covers exactly the promotion numbers."""
    return {
        "sleeve_id": sleeve_id,
        "ts": pt.get("ts"),
        "equity_usd": _num(pt.get("equity_usd")),
        "net_apy_pct": _num(pt.get("net_apy_pct")),
        "open_books": _int(pt.get("open_books")),
        "closed_books": _int(pt.get("closed_books")),
        "approvals": _int(pt.get("approvals")),
        "refusals": _int(pt.get("refusals")),
    }


def build_rows(sleeve_id: str, series: List[dict]) -> Tuple[List[dict], Optional[str]]:
    """Chain a sleeve's forward series into hash-chained rows. Returns (rows, head_hash).
    Deterministic. Empty series → ([], None) (honest empty chain)."""
    # stable date order (the series is already chronological; sort defensively).
    ordered = sorted([p for p in series if isinstance(p, dict)],
                     key=lambda p: str(p.get("date") or ""))
    rows: List[dict] = []
    prev = GENESIS_PREV
    head: Optional[str] = None
    for seq, pt in enumerate(ordered):
        date = str(pt.get("date") or "")[:10]
        payload = point_payload(sleeve_id, pt)
        entry_hash = _row_entry_hash(seq, date, payload, prev)
        rows.append({"seq": seq, "date": date, **payload,
                     "prev_hash": prev, "entry_hash": entry_hash})
        prev = entry_hash
        head = entry_hash
    return rows, head


def verify_rows(rows: List[dict]) -> dict:
    """Verify a sleeve proof chain per PROOF_CHAIN_SPEC §5 (single-genesis, contiguous seq,
    prev-linkage, self-recompute). Returns {valid, length, broken_at, head_hash}. fail-CLOSED."""
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
            recomputed = _row_entry_hash(row.get("seq"), row.get("date"),
                                         _payload_of(row), row.get("prev_hash"))
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("entry_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["entry_hash"]
        head_hash = row["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


def _load_series(series_path: Path) -> Tuple[str, List[dict]]:
    """Return (sleeve_id, series) from a *_series.json. sleeve_id falls back to the file stem."""
    try:
        doc = json.loads(series_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return series_path.stem, []
    sleeve_id = (doc.get("id") if isinstance(doc, dict) else None) or series_path.stem
    series = doc.get("series") if isinstance(doc, dict) else None
    return sleeve_id, (series if isinstance(series, list) else [])


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


def discover_series(paper_dir: Path | str | None = None) -> List[Path]:
    """Every sleeve forward-series file under the paper dir (deterministic order). A *_series.json
    that is itself the proof output is excluded by the suffix (proofs are *_series_proof.jsonl)."""
    d = Path(paper_dir) if paper_dir is not None else _PAPER_DIR
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*" + _SERIES_SUFFIX) if p.is_file())


def proof_path_for(series_path: Path) -> Path:
    """The co-located proof artifact path for a sleeve series file."""
    base = series_path.name[: -len(_SERIES_SUFFIX)]  # strip "_series.json"
    return series_path.with_name(base + _PROOF_SUFFIX)


def write_all(paper_dir: Path | str | None = None) -> List[dict]:
    """Regenerate the proof chain for EVERY discovered sleeve series and atomically write each.
    Returns one report per sleeve. Deterministic; same series → byte-identical files."""
    reports: List[dict] = []
    for series_path in discover_series(paper_dir):
        sleeve_id, series = _load_series(series_path)
        rows, head = build_rows(sleeve_id, series)
        out = proof_path_for(series_path)
        _atomic_write_rows(rows, out)
        reports.append({"sleeve_id": sleeve_id, "rows": len(rows), "head_hash": head,
                        "path": str(out), "valid": verify_rows(rows)["valid"]})
    return reports


def build_all(paper_dir: Path | str | None = None) -> Dict[str, Tuple[List[dict], Optional[str]]]:
    """Read-only build for every sleeve (for --check / refresh self-verify). Writes nothing."""
    out: Dict[str, Tuple[List[dict], Optional[str]]] = {}
    for series_path in discover_series(paper_dir):
        sleeve_id, series = _load_series(series_path)
        out[sleeve_id] = build_rows(sleeve_id, series)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.strategy_lab.rates_desk.sleeve_proof",
        description="Tamper-evident proof chains over the sleeve forward paper series (proof covers "
                    "equity/apy/book-counts + per-row prev_hash). Co-located so `verify_spa.py data/` "
                    "re-derives every sleeve.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true",
                      help="regenerate and atomically write every <sleeve>_series_proof.jsonl")
    mode.add_argument("--check", action="store_true",
                      help="recompute and print head hashes, write NOTHING")
    ap.add_argument("--paper-dir", default=None, help="dir holding the *_series.json files")
    args = ap.parse_args(argv)

    if args.build:
        reps = write_all(args.paper_dir)
        if not reps:
            print("sleeve_proof: no *_series.json found (nothing written)")
        for r in reps:
            print(f"sleeve_proof: {r['sleeve_id']}: {r['rows']} rows → {r['path']}  "
                  f"head={r['head_hash']}  valid={r['valid']}")
    else:
        built = build_all(args.paper_dir)
        if not built:
            print("sleeve_proof: no *_series.json found")
        for sid, (rows, head) in built.items():
            print(f"sleeve_proof: {sid}: {len(rows)} rows (read-only)  head={head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
