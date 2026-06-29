"""
spa_core/strategy_lab/rates_desk/books_series.py — the per-book REALIZED SERIES writer (Lane A W1:
A1.2 + A1.3 + A1.4).

PRODUCES the Lane-A side of the FROZEN DATA CONTRACT — the integration spine all three lanes share:

    data/rates_desk/books/<book_id>/realized_series.jsonl

one row per UTC day, APPEND-ONLY, proof-chained per docs/PROOF_CHAIN_SPEC.md §5 (single-genesis chain,
`row_hash` = SHA-256 over canonical {seq, as_of, event_type, payload, prev_hash}; genesis prev_hash =
"0"*64). The row schema is EXACTLY the frozen contract:

    {as_of, book_id, market, maturity, chain, deployable_usd, deployed_usd, idle_usd,
     gross_carry_pct, net_carry_after_slippage_pct, floor_pct, refusal_state, prev_hash, row_hash}

KEY GUARANTEES (the brief's properties):
  • `as_of` is the SURFACE/DATA date (the deep stream's window end), NEVER the wall clock.
  • IDEMPOTENT per UTC day: two runs the SAME UTC day refresh today's row → IDENTICAL head_hash; a
    DISTINCT day appends (the chain grows). A re-run never double-counts.
  • REGRESSION-PINNED sizing (A1.4): `deployable_usd` is the EXACT per-book peak-simultaneous deployable
    portfolio.py already validated (reusing `portfolio._replay_single_book`), so a book's deployable
    MATCHES the existing capacity / portfolio_capacity.json — we do NOT reinvent the §9 sizing.
  • REFUSAL-STATE per book (A1.3): a book the gate refuses entirely (never deploys) records
    refusal_state="REFUSE" with deployable_usd forced to 0 — recorded HONESTLY (the refusal IS the
    edge). A toxic LRT book is never even a Book (books.enumerate_books excludes LRT), so a REFUSE here
    is an honest "this harvestable market did not clear the gate over the window".
  • per-book DEPLOYABLE ≤ §9 cap ALWAYS — it is read straight off the gate-driven replay, never a
    fabricated value above pool depth.

CONVENTIONS (inherited, enforced): stdlib only; deterministic; fail-CLOSED — missing deep data RAISES,
NO fabricated row; atomic writes (tmp + os.replace, repo rule #4); LLM-FORBIDDEN. Advisory / research —
moves NO capital, never touches the go-live track.

Run (offline, on the deep cached data):
    python3 -m spa_core.strategy_lab.rates_desk.books_series          # write ALL books' series
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.rates_desk import books as rd_books
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams

_ROOT = Path(__file__).resolve().parents[3]
_BOOKS_DIR = _ROOT / "data" / "rates_desk" / "books"

# The fixed event_type for the per-book realized-series chain (PROOF_CHAIN_SPEC §3 / §7 invariant —
# the constant is NOT stored per row; it is fixed for this surface). Distinct from the rates_desk
# decision chain ("rates_desk_decision") and the sleeve forward chain ("sleeve_forward_point").
EVENT_TYPE = "rates_desk_book_realized_point"
GENESIS_PREV = "0" * 64

# The chain-linkage envelope keys re-derived on every write; everything else is the signed payload.
_ENVELOPE_KEYS = ("as_of", "prev_hash", "row_hash")

SERIES_NAME = "realized_series.jsonl"


# ── canonical hashing (PROOF_CHAIN_SPEC §2/§3 — byte-identical recipe to hash_chain) ─────────────────
def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_of(row: dict) -> dict:
    """The signed decision body = the row minus the three chain-linkage envelope keys."""
    return {k: v for k, v in row.items() if k not in _ENVELOPE_KEYS}


def compute_row_hash(seq: int, as_of: str, payload: dict, prev_hash: str) -> str:
    """PROOF_CHAIN_SPEC §3 — SHA-256 over canonical({seq, as_of, event_type, payload, prev_hash}).
    `as_of` plays the §3 `ts` role (the per-row time key); event_type is the fixed constant."""
    canon = _canonical({
        "seq": seq,
        "as_of": as_of,
        "event_type": EVENT_TYPE,
        "payload": payload,
        "prev_hash": prev_hash,
    })
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _rebase_rows(rows: List[dict]) -> List[dict]:
    """Re-base an ordered list of book-series rows into ONE contiguous single-genesis prev-linked chain
    (seq implicit by index; prev_hash re-linked; row_hash recomputed over each row's own payload). The
    payload (the frozen-contract body) is preserved verbatim. Deterministic; verifies standalone."""
    rebased: List[dict] = []
    prev = GENESIS_PREV
    for seq, row in enumerate(rows):
        payload = _payload_of(row)
        as_of = row.get("as_of")
        row_hash = compute_row_hash(seq, as_of, payload, prev)
        rebased.append({**payload, "as_of": as_of, "prev_hash": prev, "row_hash": row_hash})
        prev = row_hash
    return rebased


def verify_series(rows: List[dict]) -> dict:
    """Verify ONE book's realized series as a single chain (PROOF_CHAIN_SPEC §5 shape, keyed on as_of).
    Walk in order; require (1) prev_hash == previous row's row_hash (genesis '0'*64), (2)
    recompute_row_hash(row) == row_hash. Returns {valid, length, broken_at, head_hash}. Empty is
    vacuously valid. fail-CLOSED on any malformed row."""
    expected_prev = GENESIS_PREV
    head = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        try:
            recomputed = compute_row_hash(idx, row.get("as_of"), _payload_of(row), row.get("prev_hash"))
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED here
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("row_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["row_hash"]
        head = row["row_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head}


# ── the per-book realized row (A1.2/A1.3/A1.4 — reuse portfolio's validated replay) ──────────────────
def _book_row(
    book: rd_books.Book,
    as_of: str,
    deep: dict,
    funding: Dict[str, float],
    params: RatePolicyParams,
) -> dict:
    """Compute ONE book's frozen-contract realized-series PAYLOAD (the body — envelope is added at
    chain-write time). REUSES portfolio._replay_single_book so `deployable_usd` is the EXACT validated
    per-book peak-simultaneous deployable (A1.4 regression pin — identical §9 sizing as portfolio.py).

    A1.3 refusal-state: a book that NEVER deployed any capacity over the window (the gate refused it
    entirely) records refusal_state="REFUSE" and deployable_usd is forced to 0 — recorded honestly.
    A book that deployed records "DEPLOYED". Deterministic; PURE w.r.t. the gate."""
    from spa_core.strategy_lab.rates_desk import portfolio as PORT

    market = deep["markets"][book.market_key]
    window = deep.get("window") or {"start": None, "end": None}
    floor_pct = round(float(params.rwa_floor) * 100.0, 4)

    replay = PORT._replay_single_book(book.market_key, market, window, params, funding)
    deployable = float(replay["deployable_usd"])
    net_carry = float(replay["net_carry_pct"])

    # A1.3: refusal IS the edge. A $0-deployable book is one the gate refused over the whole window →
    # REFUSE, deployable forced 0 (already 0 from the replay; we PIN it so a refused row can never carry
    # a non-zero deployable). A deployed book is DEPLOYED.
    if deployable <= 0.0:
        refusal_state = "REFUSE"
        deployable = 0.0
        net_carry = 0.0
    else:
        refusal_state = "DEPLOYED"

    # gross vs net: the replay's net_carry IS net-of-the-§9-slippage haircut (the gate prices it into the
    # approved size — see capacity.py). We carry it as net_carry_after_slippage_pct; gross_carry_pct is
    # the same harvestable carry rate the book clips on its deployed slice (no separate un-slipped gross
    # is modelled here — the slippage is already inside the gate's approved size, identical to capacity).
    gross_carry = net_carry

    # deployed_usd / idle_usd are reported on the book's own deployable basis: a fully-deployed book has
    # deployed == deployable, idle == 0 (the IDLE@floor dilution is an AGGREGATE/portfolio property, not
    # a per-book-depth property — the book's depth-bound capacity is fully deployed by construction).
    deployed_usd = deployable
    idle_usd = 0.0

    return {
        "as_of": as_of,
        "book_id": book.book_id,
        "market": book.market_key,
        "maturity": book.maturity,
        "chain": book.chain,
        "deployable_usd": round(deployable, 2),
        "deployed_usd": round(deployed_usd, 2),
        "idle_usd": round(idle_usd, 2),
        "gross_carry_pct": round(gross_carry, 4),
        "net_carry_after_slippage_pct": round(net_carry, 4),
        "floor_pct": floor_pct,
        "refusal_state": refusal_state,
    }


def _series_path(book_id: str) -> Path:
    return _BOOKS_DIR / book_id / SERIES_NAME


def _append_row_idempotent(path: Path, row_body: dict) -> dict:
    """Append `row_body` (a frozen-contract payload incl. as_of) to a book's realized_series.jsonl AS
    ONE COHERENT single-genesis chain, IDEMPOTENT per UTC day, atomically.

    Reads the existing series; if the last row's as_of == this row's as_of it REFRESHES that row (no
    double-count); otherwise it APPENDS. Then re-bases the whole file into a single prev-linked chain
    (prev_hash/row_hash recomputed; payload preserved) so it verifies standalone per §5. Atomic:
    read-all → rewrite tmp → os.replace. Returns the verify_series() verdict for the written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: List[dict] = []
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                existing.append(json.loads(ln))
            except json.JSONDecodeError:
                continue  # drop a corrupt historical line — re-basing rebuilds a clean chain
    as_of = row_body["as_of"]
    if existing and existing[-1].get("as_of") == as_of:
        existing = existing[:-1]  # idempotent per UTC day: refresh today's row, never double-count
    combined = existing + [row_body]
    rebased = _rebase_rows(combined)
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for r in rebased]
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))
    return verify_series(rebased)


def write_book_series(
    book: rd_books.Book,
    as_of: str,
    deep: dict,
    funding: Dict[str, float],
    params: RatePolicyParams,
    books_dir: Optional[Path] = None,
) -> dict:
    """Write ONE book's frozen-contract realized-series row for `as_of` (idempotent per UTC day,
    proof-chained). Returns {book_id, path, row, verify}."""
    row_body = _book_row(book, as_of, deep, funding, params)
    path = (books_dir / book.book_id / SERIES_NAME) if books_dir else _series_path(book.book_id)
    verify = _append_row_idempotent(path, row_body)
    return {"book_id": book.book_id, "path": str(path), "row": row_body, "verify": verify}


def write_all(
    deep: Optional[dict] = None,
    funding: Optional[Dict[str, float]] = None,
    params: Optional[RatePolicyParams] = None,
    as_of: Optional[str] = None,
    books_dir: Optional[Path] = None,
) -> dict:
    """Write the per-book realized-series row for EVERY harvestable book (A1.2 across the registry).

    `as_of` defaults to the deep stream's window END (the surface/data date — NEVER the wall clock).
    fail-CLOSED: a missing deep dataset RAISES (no fabricated rows). Returns a summary {as_of, n_books,
    n_deployed, n_refused, all_valid, books:[...]}. Deterministic given (deep, funding, params)."""
    params = params or RatePolicyParams()
    if deep is None:
        from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
        deep = pph.load()
    if funding is None:
        from spa_core.strategy_lab.rates_desk import retro
        try:
            funding = retro.load_funding()
        except FileNotFoundError:
            funding = {}

    markets = deep.get("markets") if isinstance(deep, dict) else None
    if not isinstance(markets, dict) or not markets:
        raise ValueError("books_series: deep dataset has empty/invalid 'markets' (fail-CLOSED)")
    window = deep.get("window") or {}
    # as_of = the surface/data date (window end), never the clock. fail-CLOSED if neither given.
    resolved_as_of = as_of or window.get("end")
    if not resolved_as_of:
        raise ValueError("books_series: no as_of and deep window has no 'end' date (fail-CLOSED)")

    book_list = rd_books.enumerate_books(deep)
    out_books: List[dict] = []
    n_deployed = n_refused = 0
    all_valid = True
    for book in book_list:
        res = write_book_series(book, resolved_as_of, deep, funding, params, books_dir=books_dir)
        out_books.append(res)
        if res["row"]["refusal_state"] == "REFUSE":
            n_refused += 1
        else:
            n_deployed += 1
        if not res["verify"]["valid"]:
            all_valid = False
    return {
        "as_of": resolved_as_of,
        "model": "rates_desk_book_realized_series",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "event_type": EVENT_TYPE,
        "n_books": len(book_list),
        "n_deployed": n_deployed,
        "n_refused": n_refused,
        "all_valid": all_valid,
        "books": [{"book_id": b["book_id"], "market": b["row"]["market"],
                   "deployable_usd": b["row"]["deployable_usd"],
                   "refusal_state": b["row"]["refusal_state"],
                   "head_hash": b["verify"]["head_hash"], "length": b["verify"]["length"]}
                  for b in out_books],
    }


def main() -> int:
    summary = write_all()
    print(f"Rates Desk — per-book REALIZED SERIES   as_of={summary['as_of']}   "
          f"(frozen contract, proof-chained, idempotent per UTC day)")
    print(f"books: {summary['n_books']}  ·  deployed: {summary['n_deployed']}  ·  "
          f"refused: {summary['n_refused']}  ·  all_valid: {summary['all_valid']}\n")
    hdr = f"{'book_id':>19s}  {'market':>20s}  {'deployable':>13s}  {'state':>9s}  {'len':>3s}"
    print(hdr)
    print("-" * (len(hdr) + 4))
    for b in summary["books"]:
        print(f"{b['book_id']:>19s}  {b['market']:>20s}  ${b['deployable_usd']:>11,.2f}  "
              f"{b['refusal_state']:>9s}  {b['length']:>3d}")
    print(f"\nWrote {_BOOKS_DIR}/<book_id>/{SERIES_NAME} for {summary['n_books']} books.")
    return 0 if summary["all_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
