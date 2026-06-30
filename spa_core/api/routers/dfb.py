"""DFB — DeFi Board router (LANE 2): the public, risk-first pool-analytics surface.

Serves Lane 1's per-pool risk overlay (`spa_core/dfb/*` engine → `data/dfb/*`) over HTTP:
every pool carries its A/B/C/D class, exit-liquidity-by-size schedule, deterministic
refusal verdict, and a reproducible per-row proof hash. "DeBank shows you the yield;
DFB shows you the RISK behind it — provably. Don't trust us, check us."

This router is a PRESENTATION layer only — it SERVES Lane 1's output VERBATIM and never
re-derives risk math (no fork — `test_dfb_no_fork` enforces that on the engine side).
It mirrors the rates_desk router's contracts byte-for-byte:

  • Read-only, GET-only, PUBLIC (a public analytics product). Auth gates only the
    mutating/LLM endpoints (api_security); the rate-limit + CORS allow-list middleware
    already apply app-wide (WS2 posture) — nothing extra to wire here.
  • Fail-CLOSED, never fabricated: a missing/corrupt pools.json → 200 + an honest
    "unavailable" payload (empty list + note), NEVER a 500, NEVER a synthesized
    leaderboard. An unknown pool_id → 404 (a guess is a lie). A pool flagged
    insufficient-exit-liquidity serves its NULL/flagged cell verbatim — never a
    fabricated absorbable number.
  • NaN/inf scrubbed before serialization (corrupt state must not crash the serializer).
  • The proof / full-chain surface serves the COMPLETE per-pool chain VERBATIM (uncapped,
    raw bytes) so a third party can re-derive the proof_hash on a clean machine — mirrors
    the rates_desk full-chain download pattern.
  • Advisory stamps on every payload (read-only analytics, not financial advice).

SHARED CONTRACT (consumed from Lane 1; built against a documented fixture matching this
schema until Lane 1 ships the live files):

  data/dfb/pools.json                  — list[ <pool overlay object> ]
  data/dfb/pool/<pool_id>.json         — one pool's full detail (overlay object)
  data/dfb/history/<pool_id>.jsonl     — proof-chained historical series (one JSON row/line)

  pool overlay object = {
    pool_id, protocol, chain, asset, tier,
    apy: {total, base, reward}, tvl_usd,
    risk_class (A/B/C/D), structural_haircut, total_haircut,
    exit_liquidity: [ {ticket_usd, absorbable_usd, dex_exit_frac, flagged} ],
    refusal: {verdict, reason, tail_veto},
    as_of, data_source, feed_coverage, prev_hash, row_hash
  }

stdlib-only (FastAPI is the documented exception); deterministic; LLM-FORBIDDEN; no
`execution/` import; never writes any file.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from spa_core.api._shared import (
    data_dir,
    now,
    parse_log_line,
    read_state,
    scrub_nonfinite,
)

log = logging.getLogger("spa.api")

router = APIRouter(tags=["dfb"])

# pool_id whitelist: filesystem-safe ids only (defense-in-depth path-traversal guard —
# a request like `../../secret` must NEVER resolve to a file outside data/dfb/). The
# overlay objects mint ids from protocol/chain/asset, so this charset is generous enough.
_POOL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")

# A decision/history line that is not valid JSON or carries a non-finite number is mapped
# to the corrupt-row surrogate so it FAILS chain re-derivation (and is never echoed as a
# serializer-crashing non-finite float). Mirrors the rates_desk _CORRUPT contract.
_CORRUPT = object()
_CORRUPT_ROW = {"__corrupt__": True}

# Advisory envelope — every DFB surface carries it (read-only analytics, NOT advice).
_DISCLAIMER = (
    "DFB is read-only risk analytics — advisory, NOT financial advice, NOT a "
    "recommendation, NOT realized capital. Numbers are served verbatim from the "
    "deterministic risk overlay; exit-liquidity is a CONSERVATIVE lower bound or a "
    "visible hole, never a fabricated fill."
)

# ── The reproducibility contract (mirror rates_desk) ────────────────────────────────────
_SPEC_VERSION = "1.0"
_CANONICAL_JSON_RULE = (
    "json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)"
)


def _reproduce_block(files: list, note: str) -> dict:
    """The self-describing 'don't trust us, check us' block embedded in every proof response."""
    return {
        "spec_version": _SPEC_VERSION,
        "spec": "docs/PROOF_CHAIN_SPEC.md",
        "canonical_json_rule": _CANONICAL_JSON_RULE,
        "hash": "sha256(canonical_json).hexdigest()",
        "public_files": files,
        "verify_with": "python3 verify_spa.py " + " ".join(files),
        "verifier": "scripts/verify_spa.py (zero-dependency, no spa_core import)",
        "note": note,
    }


def _valid_pool_id(pool_id: str) -> bool:
    """True iff pool_id is a safe id (no path traversal, bounded charset)."""
    return bool(_POOL_ID_RE.match(pool_id))


def _read_pools_list() -> list:
    """Load data/dfb/pools.json as a list of overlay objects, fail-CLOSED.

    Returns [] if missing/corrupt OR if the payload is not a JSON array — an honest
    empty universe, NEVER a fabricated leaderboard. Non-dict elements are dropped
    (an overlay row is an object). NaN/inf is scrubbed by the caller before serialize.
    """
    raw = read_state("dfb/pools.json", [])
    # The Lane-1 overlay writer wraps the rows: {generated_at, schema, n_pools, …, pools:[…]}.
    # Accept BOTH that wrapped form AND a bare list (fixtures/older writers) — fail-CLOSED.
    if isinstance(raw, dict):
        raw = raw.get("pools", [])
    if not isinstance(raw, list):
        # A corrupt pools.json that parsed to a scalar (or a dict w/o pools[]) → honest empty.
        return []
    return [p for p in raw if isinstance(p, dict)]


# ──────────────────────────────────────────────────────────────────────────────────────
# GET /api/dfb/pools — the screener list (full overlay rows, served VERBATIM)
# ──────────────────────────────────────────────────────────────────────────────────────
@router.get("/api/dfb/pools")
def get_dfb_pools():
    """DFB SCREENER — every followed pool with its full risk-overlay row.

    The client sorts/filters this list locally; we serve the COMPLETE list verbatim from
    data/dfb/pools.json (each row: protocol · chain · asset · tier · apy{total/base/reward}
    · tvl_usd · risk_class A/B/C/D · structural/total haircut · exit-liquidity-by-size ·
    refusal verdict · row_hash). Read-only, fail-CLOSED: a missing/corrupt pools.json → 200
    with an honest empty list + an `unavailable` note (NEVER a 500, NEVER a fabricated
    leaderboard). is_advisory ALWAYS true; NaN/inf scrubbed."""
    pools = _read_pools_list()
    available = bool(pools)
    return scrub_nonfinite({
        "generated_at": now(),
        "model": "dfb_pool_screener",
        "is_advisory": True,
        "available": available,
        "n_pools": len(pools),
        "pools": pools,
        "note": (
            None if available
            else "DFB pool universe unavailable — data/dfb/pools.json missing or "
                 "corrupt. No fabricated rows are served (fail-CLOSED)."
        ),
        "disclaimer": _DISCLAIMER,
        "reproduce": _reproduce_block(
            ["dfb/pools.json"],
            "Each row carries its own row_hash over its canonical-JSON payload; re-derive "
            "per PROOF_CHAIN_SPEC.md to confirm no overlay cell was back-fitted."),
    })


# ──────────────────────────────────────────────────────────────────────────────────────
# GET /api/dfb/pool/{pool_id} — one pool's full detail (404 on unknown id)
# ──────────────────────────────────────────────────────────────────────────────────────
@router.get("/api/dfb/pool/{pool_id}")
def get_dfb_pool(pool_id: str):
    """ONE pool's full DETAIL — the overlay object + its exit-liquidity schedule + refusal
    decomposition, served VERBATIM from data/dfb/pool/<pool_id>.json.

    Fail-CLOSED:
      • an invalid/path-traversing pool_id → 404 (we never resolve outside data/dfb/);
      • an UNKNOWN pool_id → 404 (a guess is a lie — we do NOT fabricate a pool);
      • a pool flagged insufficient-exit-liquidity serves its NULL/flagged exit cell
        VERBATIM — never a synthesized absorbable number.
    is_advisory ALWAYS true; NaN/inf scrubbed."""
    if not _valid_pool_id(pool_id):
        raise HTTPException(status_code=404, detail={
            "error": "unknown_pool",
            "pool_id": pool_id,
            "note": "fail-CLOSED: invalid pool_id; no pool is fabricated.",
        })
    raw = read_state(f"dfb/pool/{pool_id}.json", None)
    if not isinstance(raw, dict) or not raw:
        raise HTTPException(status_code=404, detail={
            "error": "unknown_pool",
            "pool_id": pool_id,
            "note": "fail-CLOSED: no detail for this pool_id; absence is honest, not a guess.",
        })
    raw.setdefault("is_advisory", True)
    raw.setdefault("disclaimer", _DISCLAIMER)
    raw.setdefault("reproduce", _reproduce_block(
        [f"dfb/pool/{pool_id}.json"],
        "This pool's row_hash is reproducible over its canonical-JSON payload per "
        "PROOF_CHAIN_SPEC.md; exit-liquidity cells are conservative lower bounds or "
        "explicit holes (flagged), never fabricated fills."))
    return scrub_nonfinite(raw)


# ──────────────────────────────────────────────────────────────────────────────────────
# GET /api/dfb/pool/{pool_id}/history — proof-chained historical series
# ──────────────────────────────────────────────────────────────────────────────────────
@router.get("/api/dfb/pool/{pool_id}/history")
def get_dfb_pool_history(
    pool_id: str,
    limit: int = Query(default=365, ge=1, le=2000),
):
    """ONE pool's proof-chained HISTORICAL series (APY/TVL/refusal-state over time).

    Reads data/dfb/history/<pool_id>.jsonl (one captured record per UTC day, chained via
    prev_hash/row_hash) and VERIFIES it as one chain before returning. The refusal-state
    timeline is the scarce asset DFB captures day-1. Read-only, fail-CLOSED: an absent
    history → 200 with an empty, vacuously-valid chain (NEVER a 500), but an invalid
    pool_id → 404. Most-recent rows last (bounded by limit). NaN/inf scrubbed."""
    if not _valid_pool_id(pool_id):
        raise HTTPException(status_code=404, detail={
            "error": "unknown_pool",
            "pool_id": pool_id,
            "note": "fail-CLOSED: invalid pool_id; no history is fabricated.",
        })
    path = data_dir() / "dfb" / "history" / f"{pool_id}.jsonl"
    rows: list = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                parsed = parse_log_line(ln, corrupt_marker=_CORRUPT)
                # fail-CLOSED: drop non-JSON / non-finite / non-dict lines — a history
                # record is a JSON object; a corrupt line is surfaced via chain.verified.
                rows.append(_CORRUPT_ROW if parsed is _CORRUPT else parsed)
        except OSError as e:
            log.warning(f"dfb history read failed for {pool_id}: {e}")

    chain = _verify_history_chain(rows)

    # Public projection: drop corrupt surrogates from the returned series (the chain badge
    # already reports verified=false + broken_at if any line was corrupt), bound by limit.
    series = [r for r in rows if isinstance(r, dict) and not r.get("__corrupt__")]
    series = series[-limit:]

    return scrub_nonfinite({
        "generated_at": now(),
        "model": "dfb_pool_history",
        "is_advisory": True,
        "pool_id": pool_id,
        "n_records": len(series),
        "chain": {
            "verified": bool(chain["valid"]),
            "chain_length": chain["length"],
            "head_hash": chain["head_hash"],
            "broken_at": chain["broken_at"],
            "spec": "docs/PROOF_CHAIN_SPEC.md",
        },
        "series": series,
        "disclaimer": _DISCLAIMER,
        "reproduce": _reproduce_block(
            [f"dfb/history/{pool_id}.jsonl"],
            "Re-derive each row_hash and the head from the JSONL per PROOF_CHAIN_SPEC.md; "
            "the chain.verified/head_hash above reproduce byte-for-byte under the verifier."),
    })


# ──────────────────────────────────────────────────────────────────────────────────────
# GET /api/dfb/pool/{pool_id}/proof — the per-pool proof chain VERBATIM (uncapped)
# ──────────────────────────────────────────────────────────────────────────────────────
@router.get("/api/dfb/pool/{pool_id}/proof", response_class=PlainTextResponse)
def get_dfb_pool_proof(pool_id: str):
    """The per-pool PROOF CHAIN, served COMPLETE and VERBATIM (raw bytes, NO cap, NO
    reformat) so a third party can re-derive the proof_hash on a clean machine.

    Mirrors the rates_desk full-chain download surface (audit finding #1): /history is
    CAPPED (limit≤2000) for a human glance, but a skeptic who wants to RE-DERIVE the head
    with scripts/verify_spa.py needs EVERY byte of data/dfb/history/<pool_id>.jsonl. This
    streams the entire artifact unchanged (text/plain; JSONL is not one JSON document, so a
    JSON response would reframe it). Read-only, fail-CLOSED:
      • an invalid/unknown pool_id → 404 (never a fabricated body);
      • a KNOWN pool with no captured history file yet → 404 (absence is an honest
        condition the verifier should see, NOT a silent empty pass).
    NO secret/state ever lives in this file."""
    if not _valid_pool_id(pool_id):
        raise HTTPException(status_code=404, detail={
            "error": "unknown_pool",
            "pool_id": pool_id,
            "note": "fail-CLOSED: invalid pool_id; no chain is fabricated.",
        })
    path = data_dir() / "dfb" / "history" / f"{pool_id}.jsonl"
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail={
            "error": "pool_proof_absent",
            "pool_id": pool_id,
            "file": f"dfb/history/{pool_id}.jsonl",
            "note": "fail-CLOSED: no proof chain captured for this pool yet; no fabricated "
                    "or empty body is served.",
        })
    return PlainTextResponse(content=raw, media_type="text/plain; charset=utf-8")


# ──────────────────────────────────────────────────────────────────────────────────────
# GET /api/dfb/summary — universe stats for the screener header
# ──────────────────────────────────────────────────────────────────────────────────────
@router.get("/api/dfb/summary")
def get_dfb_summary():
    """DFB UNIVERSE STATS for the screener header — n pools, n by risk class (A/B/C/D),
    n refused, n with exit-liquidity at $1M, as_of.

    Derived (counts only — NO risk math here, just aggregation of Lane 1's verdicts) from
    data/dfb/pools.json. Read-only, fail-CLOSED: a missing/corrupt universe → 200 with
    zeroed counts + an `unavailable` note (NEVER a 500). is_advisory ALWAYS true."""
    pools = _read_pools_list()
    available = bool(pools)

    by_class = {"A": 0, "B": 0, "C": 0, "D": 0, "UNKNOWN": 0}
    n_refused = 0
    n_exit_1m = 0  # pools that ABSORB a $1M exit ticket (a real flagged-false fill)
    latest_as_of = None

    for p in pools:
        rc = p.get("risk_class")
        if rc in by_class:
            by_class[rc] += 1
        else:
            by_class["UNKNOWN"] += 1

        refusal = p.get("refusal")
        if isinstance(refusal, dict) and refusal.get("verdict") == "REFUSE":
            n_refused += 1

        # "exit-liquidity at $1M" = a $1M ticket that is NOT flagged AND has a concrete
        # absorbable number. A flagged/NULL cell is a HOLE, never counted as absorbable.
        exits = p.get("exit_liquidity")
        if isinstance(exits, list):
            for t in exits:
                if not isinstance(t, dict):
                    continue
                if t.get("ticket_usd") == 1_000_000:
                    absorb = t.get("absorbable_usd")
                    if not t.get("flagged") and isinstance(absorb, (int, float)):
                        n_exit_1m += 1
                    break

        as_of = p.get("as_of")
        if isinstance(as_of, str) and (latest_as_of is None or as_of > latest_as_of):
            latest_as_of = as_of

    return scrub_nonfinite({
        "generated_at": now(),
        "model": "dfb_universe_summary",
        "is_advisory": True,
        "available": available,
        "n_pools": len(pools),
        "n_by_risk_class": by_class,
        "n_refused": n_refused,
        "n_exit_liquidity_1m": n_exit_1m,
        "as_of": latest_as_of,
        "note": (
            None if available
            else "DFB universe unavailable — data/dfb/pools.json missing or corrupt. "
                 "Counts are zeroed (fail-CLOSED), not fabricated."
        ),
        "disclaimer": _DISCLAIMER,
    })


# ──────────────────────────────────────────────────────────────────────────────────────
# Chain verification (delegates to the shared proof_chain verifier — NEVER forks the math)
# ──────────────────────────────────────────────────────────────────────────────────────
def _verify_history_chain(rows: list) -> dict:
    """Verify a per-pool history JSONL as ONE chain via the SHARED engine verifier.

    DFB does NOT define its own chain math — it composes the engine's
    ``books_series.verify_series`` (the SAME prev_hash/row_hash verifier the rates-desk
    book series uses, keyed on the per-row `as_of` time field — exactly the DFB history
    contract: each record carries `prev_hash` + `row_hash`). So the desk and DFB agree to
    the byte: walk in order, require prev_hash == previous.row_hash (genesis "0"*64), and
    recompute_row_hash(row) == row_hash; head = the last row's hash. fail-CLOSED if the
    verifier is unavailable OR any row is malformed (corrupt surrogate rows have no
    row_hash → break the chain, which is the honest tamper-evident outcome). An
    empty/absent history is vacuously valid (length 0)."""
    try:
        from spa_core.strategy_lab.rates_desk import books_series
    except Exception as e:  # noqa: BLE001 — fail-CLOSED if the integrity module is unavailable
        log.warning(f"dfb history: books_series import failed: {e}")
        return {"valid": False, "length": len(rows), "broken_at": None, "head_hash": None}
    try:
        return books_series.verify_series(rows)
    except Exception as e:  # noqa: BLE001 — graceful, never 500
        log.warning(f"dfb history: chain verify failed: {e}")
        return {"valid": False, "length": len(rows), "broken_at": None, "head_hash": None}
