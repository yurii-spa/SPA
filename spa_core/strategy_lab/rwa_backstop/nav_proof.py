#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core.strategy_lab.rwa_backstop.nav_proof — tamper-evident proof chain over the
RWA-BACKSTOP NAV FORWARD RECORD (WORKSTREAM 2 proof-breadth, 2026-06-28).

Why this exists
===============
``nav_curve.py`` appends one MEASURED-NAV forward point per UTC day to
``data/rwa_nav_curve.json`` — but those points carried NO proof. A producer could silently
back-edit ``tvl_weighted_nav`` / ``liq_nav_gap_pct`` (the headline marketing-vs-liquidation
gap), drop a day, or reorder the series, and nothing would diverge. This module applies the
PROVEN exit-NAV proof pattern (PROOF_CHAIN_SPEC §6) to each forward point: a per-row
``proof_hash`` over ``{inputs, outputs, prev_hash}`` that CHAINS the points.

  * **FAIL#2 lesson (red-team):** the proof covers the OUTPUTS (``tvl_weighted_nav`` /
    ``liq_nav_gap_pct`` / the measurement counts), not just the date. Forging any published
    NAV number diverges the recompute. Every row also carries a ``prev_hash`` linking it to the
    previous row's ``proof_hash`` (genesis ``"0"*64``), so REORDERING / dropping / inserting a
    forward point breaks the chain — the verifier reports the precise ``first_bad`` / ``broken_at``.
  * **F1 lesson (anti-rot):** the published proof artifact is REGENERATED from the producer's
    latest series whenever the producer advances (folded into the safety-board agent + the
    published proof refresh), so it never goes stale relative to ``rwa_nav_curve.json``.

The artifact is ``data/rwa_backstop/nav_proof.jsonl`` — co-located so the SAME one-line command
(``python3 scripts/verify_spa.py data/``) auto-discovers and re-derives it, with NO ``spa_core``
on the reviewer's machine.

Chain recipe (deterministic, documented for independent re-derivation)
======================================================================
Each line is one forward point. Two groups + a chain envelope:

* ``inputs``  = ``{date, ts, n_assets, onchain_4626_count, off_chain_estimate_count}``
  (the measurement provenance — which day, how many assets, how many had a real on-chain
  ERC-4626 NAV vs an off-chain estimate).
* ``outputs`` = ``{tvl_weighted_nav, liq_nav_gap_pct}`` (the user-facing measured numbers).
* ``prev_hash`` links the row to the previous row's ``proof_hash`` (genesis ``"0"*64``).
* ``proof_hash = sha256(canonical({inputs, outputs, prev_hash}))`` — the EXACT exit-NAV recipe
  (``json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)``), so the standalone
  verifier reuses the same recompute. A forged output, or a reordered/dropped/inserted row,
  diverges the recompute / breaks the linkage.

Scope / safety
==============
* Stdlib only. Deterministic. No LLM, no randomness, no network.
* Atomic writes (tmp + os.replace). Read-only over ``rwa_nav_curve.json`` — never mutates it.
* Advisory / RESEARCH only: moves no capital, touches no risk/execution, no go-live track.

CLI::

    python3 -m spa_core.strategy_lab.rwa_backstop.nav_proof --build   # write the proof artifact
    python3 -m spa_core.strategy_lab.rwa_backstop.nav_proof --check   # recompute, print head
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
GENESIS_PREV = "0" * 64
NAV_PROOF_INPUT_KEYS = ("date", "ts", "n_assets", "onchain_4626_count", "off_chain_estimate_count")
NAV_PROOF_OUTPUT_KEYS = ("tvl_weighted_nav", "liq_nav_gap_pct")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CURVE = _REPO_ROOT / "data" / "rwa_nav_curve.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "rwa_backstop" / "nav_proof.jsonl"


def _proof_hash(proof_obj: dict) -> str:
    """sha256 over the canonical sorted-JSON of {inputs, outputs, prev_hash} — the EXACT exit-NAV
    §6 recipe (default=str; published values are JSON-native so byte-identical either way)."""
    blob = json.dumps(proof_obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError, OverflowError):
            return None
        return f if f == f else None  # drop NaN
    return None


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def point_proof_obj(point: dict, prev_hash: str) -> dict:
    """Reconstruct the §6 hashed object {inputs, outputs, prev_hash} from a forward point.
    Deterministic; the SAME shape the verifier reconstructs from the published row."""
    return {
        "inputs": {
            "date": point.get("date"),
            "ts": point.get("ts"),
            "n_assets": _int(point.get("n_assets")),
            "onchain_4626_count": _int(point.get("onchain_4626_count")),
            "off_chain_estimate_count": _int(point.get("off_chain_estimate_count")),
        },
        "outputs": {
            "tvl_weighted_nav": _num(point.get("tvl_weighted_nav")),
            "liq_nav_gap_pct": _num(point.get("liq_nav_gap_pct")),
        },
        "prev_hash": prev_hash,
    }


def build_rows(series: List[dict]) -> Tuple[List[dict], Optional[str]]:
    """Chain the forward series into proof rows. Returns (rows, head_hash). Deterministic.
    Each row carries its published inputs+outputs verbatim, ``prev_hash`` (chained), and the
    recomputed ``proof_hash``. Empty series → ([], None) (honest empty chain)."""
    rows: List[dict] = []
    prev = GENESIS_PREV
    head: Optional[str] = None
    for pt in series:
        if not isinstance(pt, dict):
            continue
        proof_obj = point_proof_obj(pt, prev)
        ph = _proof_hash(proof_obj)
        row = {
            **proof_obj["inputs"],
            **proof_obj["outputs"],
            "prev_hash": prev,
            "proof_hash": ph,
        }
        rows.append(row)
        prev = ph
        head = ph
    return rows, head


def verify_rows(rows: List[dict]) -> dict:
    """Verify the NAV proof chain: each row's proof_hash recomputes from its {inputs, outputs,
    prev_hash}, and the prev_hash links to the previous row's proof_hash (genesis '0'*64).
    Returns {valid, length, broken_at, head_hash}. Empty is vacuously valid. fail-CLOSED."""
    expected_prev = GENESIS_PREV
    head_hash: Optional[str] = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        try:
            recomputed = _proof_hash(point_proof_obj(row, row.get("prev_hash")))
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("proof_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["proof_hash"]
        head_hash = row["proof_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


def _load_series(curve_path: Path) -> List[dict]:
    try:
        doc = json.loads(curve_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    series = doc.get("series") if isinstance(doc, dict) else None
    return series if isinstance(series, list) else []


def _atomic_write_rows(rows: List[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
                   for r in rows)
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


def write_proof(curve_path: Path | str | None = None,
                out_path: Path | str | None = None) -> dict:
    """Regenerate the NAV proof chain from the CURRENT forward series and atomically write it.
    Returns a small report. Deterministic; same series → byte-identical file."""
    cpath = Path(curve_path) if curve_path is not None else _DEFAULT_CURVE
    out = Path(out_path) if out_path is not None else _DEFAULT_OUT
    series = _load_series(cpath)
    rows, head = build_rows(series)
    _atomic_write_rows(rows, out)
    return {"rows": len(rows), "head_hash": head, "path": str(out),
            "valid": verify_rows(rows)["valid"]}


def build_chain(curve_path: Path | str | None = None) -> Tuple[List[dict], Optional[str]]:
    """Read-only build (for --check / refresh self-verify). Writes nothing."""
    cpath = Path(curve_path) if curve_path is not None else _DEFAULT_CURVE
    return build_rows(_load_series(cpath))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.strategy_lab.rwa_backstop.nav_proof",
        description="Tamper-evident proof chain over the RWA-backstop NAV forward record "
                    "(per-row proof_hash over inputs+outputs+prev_hash; exit-NAV pattern). "
                    "Co-located so `verify_spa.py data/` re-derives it.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true",
                      help="regenerate and atomically write data/rwa_backstop/nav_proof.jsonl")
    mode.add_argument("--check", action="store_true",
                      help="recompute and print the head hash, write NOTHING")
    ap.add_argument("--curve", default=None, help="path to rwa_nav_curve.json")
    ap.add_argument("--out", default=None, help="output JSONL path")
    args = ap.parse_args(argv)

    if args.build:
        rep = write_proof(args.curve, args.out)
        print(f"nav_proof: wrote {rep['rows']} forward-point rows → {rep['path']}")
        print(f"nav_proof: head_hash={rep['head_hash']}  valid={rep['valid']}")
    else:
        rows, head = build_chain(args.curve)
        print(f"nav_proof: {len(rows)} forward-point rows (read-only, nothing written)")
        print(f"nav_proof: head_hash={head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
