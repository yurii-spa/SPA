"""Rates-Desk router — RateSurface, opportunity scan, decision log, tamper-evident
PROOF chain, and the live paper forward-track.

Behavior-preserving extraction from server.py. NOTE: in the monolith these routes
carried tags=["strategy_lab"], so the router keeps that tag to preserve the exact
OpenAPI tag grouping. All payloads + the hash-chain verification are byte-identical.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from spa_core.api._shared import (
    backtest_meta,
    data_dir,
    now,
    parse_log_line,
    read_state,
    scrub_nonfinite,
)

log = logging.getLogger("spa.api")

router = APIRouter(tags=["strategy_lab"])

# Sentinel for a decision-log line that is not valid JSON OR carries a non-finite (NaN/inf)
# number. In the machine /decisions view such a line is simply dropped; in the tamper-evident
# /proof and /refusals views it is mapped to the corrupt-row surrogate so it FAILS chain
# re-derivation (and is never echoed as a serializer-crashing non-finite float).
_CORRUPT = object()
_CORRUPT_ROW = {"__corrupt__": True}

# ── The API reproducibility contract (A4) ────────────────────────────────────────────────────────
# Every proof-bearing response embeds this `reproduce` block so the MACHINE RESPONSE TEACHES ITS OWN
# VERIFICATION: a consumer learns the spec version, the exact canonical-JSON rule, and the single
# command to re-derive every hash WITHOUT our code. The server verdict (verified / head_hash /
# proof_hash) MUST match scripts/verify_spa.py byte-for-byte on the same public files.
_SPEC_VERSION = "1.0"
_CANONICAL_JSON_RULE = "json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)"


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


@router.get("/api/rates-desk/surface")
def get_rates_desk_surface():
    """Rates-Desk current RateSurface — data/rates_desk/rate_surface.json.

    Read-only, graceful: served VERBATIM; empty payload when missing/corrupt.
    """
    _surface_meta = backtest_meta(
        basis="implied/fixed-rate surface from live PT/lending feeds + deep Pendle PT "
              "history 2024-01→2026-06; quoted rates are research, not realized P&L",
        period="current surface (see as_of); history 2024-01→2026-06",
    )
    raw = read_state("rates_desk/rate_surface.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None, "as_of": None, "mode": None,
            "hedge_available": {}, "quotes": [], "underlying_risk": {},
            "meta": _surface_meta,
        }
    raw.setdefault("meta", _surface_meta)
    # fail-CLOSED: a corrupt surface carrying a NaN/inf number must not crash the serializer.
    return scrub_nonfinite(raw)


@router.get("/api/rates-desk/opportunities")
def get_rates_desk_opportunities():
    """Rates-Desk current opportunity scan — the four trade shapes ranked by net_edge.

    Built from the cached RateSurface via the pure OpportunityEngine. Read-only, graceful:
    returns an empty payload when the surface is missing/corrupt or the scan cannot be built.
    """
    _opp_meta = backtest_meta(
        basis="ranked trade shapes scanned from the cached rate surface (deep Pendle PT "
              "history 2024-01→2026-06, total-capital basis, capacity-constrained); "
              "net_edge is research, not realized P&L",
        period="current scan (see as_of); history 2024-01→2026-06",
    )
    raw = read_state("rates_desk/rate_surface.json", {})
    empty = {"generated_at": None, "as_of": None, "n_opportunities": 0,
             "opportunities": [], "meta": _opp_meta}
    if not raw or not isinstance(raw, dict) or not raw.get("quotes"):
        return empty
    try:
        from spa_core.strategy_lab.rates_desk.surface_io import scan_cached_surface
        scan = scan_cached_surface(raw)
        if isinstance(scan, dict):
            scan.setdefault("meta", _opp_meta)
        return scrub_nonfinite(scan)
    except Exception as e:  # noqa: BLE001 — graceful, never 500 the dashboard
        log.warning(f"rates-desk opportunities scan failed: {e}")
        return empty


@router.get("/api/rates-desk/decisions")
def get_rates_desk_decisions(limit: int = Query(default=50, ge=1, le=500)):
    """Rates-Desk recent decision log — data/rates_desk/decision_log.jsonl (incl. REFUSALS).

    Read-only, graceful: returns an empty list when the log is absent. Most recent last.
    """
    path = (data_dir() / "rates_desk" / "decision_log.jsonl")
    rows = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                parsed = parse_log_line(ln, corrupt_marker=_CORRUPT)
                # fail-CLOSED: drop non-JSON / non-finite / non-dict lines — a decision row is a
                # JSON object; a bare scalar/list is not a decision and must not crash the counts.
                if parsed is _CORRUPT or not isinstance(parsed, dict):
                    continue
                rows.append(parsed)
        except OSError as e:
            log.warning(f"rates-desk decision log read failed: {e}")
    rows = rows[-limit:]
    counts = {"ENTRY": 0, "REFUSAL": 0}
    for r in rows:
        k = r.get("kind")
        if k in counts:
            counts[k] += 1
    return {
        "generated_at": now(),
        "model": "rates_desk_decision_log",
        "n_decisions": len(rows),
        "counts": counts,
        "decisions": rows,
    }


def _verify_decision_log(rows: list) -> dict:
    """Verify the public decision_log mirror as ONE chain, EXACTLY per docs/PROOF_CHAIN_SPEC.md §5.

    Delegates to the single shared verifier ``proof_chain.verify_mirror`` so that the API verdict,
    the published spec recipe, and the smoke test compute the IDENTICAL result on the same file: walk
    in seq order requiring ``seq == idx``, ``prev_hash == previous.entry_hash`` (genesis ``"0"*64``),
    and ``recompute_entry_hash(row) == entry_hash``; ``head_hash`` = the LAST row's entry_hash. This
    REJECTS a forged/unlinked row (e.g. a fabricated seq:999 with a bogus prev_hash) → verified:false
    with the correct broken_at, and never lets it become the published head_hash. fail-CLOSED if the
    verifier is unavailable. An empty log is vacuously valid.
    """
    try:
        from spa_core.strategy_lab.rates_desk import proof_chain
    except Exception as e:  # noqa: BLE001 — fail-CLOSED if the integrity module is unavailable
        log.warning(f"rates-desk proof: proof_chain import failed: {e}")
        return {"valid": False, "length": len(rows), "broken_at": None, "head_hash": None}
    return proof_chain.verify_mirror(rows)


@router.get("/api/rates-desk/proof")
def get_rates_desk_proof(last_n: int = Query(default=12, ge=1, le=200)):
    """Rates-Desk PROOF surface — publicly verifiable, tamper-evident decision chain.

    Actually RUNS the chain verification on data/rates_desk/decision_log.jsonl. Read-only, graceful,
    fail-CLOSED: an absent/corrupt log yields verified=true over a length-0 chain, never a 500.
    """
    path = (data_dir() / "rates_desk" / "decision_log.jsonl")
    rows: list = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                parsed = parse_log_line(ln, corrupt_marker=_CORRUPT)
                rows.append(_CORRUPT_ROW if parsed is _CORRUPT else parsed)
        except OSError as e:
            log.warning(f"rates-desk proof: decision log read failed: {e}")

    result = _verify_decision_log(rows)

    counts = {"ENTRY": 0, "REFUSAL": 0}
    for r in rows:
        if isinstance(r, dict):
            k = r.get("kind")
            if k in counts:
                counts[k] += 1

    last = []
    for r in rows[-last_n:]:
        if not isinstance(r, dict):
            continue
        dec = r.get("decomposition") or {}
        last.append({
            "seq": r.get("seq"),
            "ts": r.get("ts"),
            "as_of": r.get("as_of"),
            "underlying": r.get("underlying") or dec.get("underlying"),
            "kind": r.get("kind"),
            "allowed": bool(r.get("approved")),
            "reason": (r.get("detail", {}) or {}).get("note") or r.get("reason"),
            "haircut_total": dec.get("total_haircut"),
            "net_edge": r.get("net_edge"),
            "payload_hash": r.get("proof_hash"),
            "entry_hash": r.get("entry_hash"),
        })

    # ── cross-eviction anchor badge (A3): the append-only checkpoint ledger over the public head ──
    anchor_badge = {"verified": True, "length": 0, "broken_at": None, "latest_matches_head": None}
    try:
        from spa_core.strategy_lab.rates_desk import anchors as _anchors
        av = _anchors.verify_anchors()
        anchor_badge = {
            "verified": bool(av["valid"]),
            "length": av["length"],
            "broken_at": av["broken_at"],
            "latest_matches_head": av["latest_matches_head"],
        }
    except Exception as e:  # noqa: BLE001 — graceful, never 500 the dashboard
        log.warning(f"rates-desk proof: anchor verify failed: {e}")
        anchor_badge["verified"] = False

    return {
        "generated_at": now(),
        "model": "rates_desk_proof_chain",
        "chain_length": result["length"],
        "head_hash": result["head_hash"],
        "verified": result["valid"],
        "broken_at": result["broken_at"],
        "counts": counts,
        "anchors": anchor_badge,
        "last_n_decisions": last,
        "reproduce": _reproduce_block(
            ["decision_log.jsonl", "anchors.jsonl"],
            "Re-derive every entry_hash + head_hash per PROOF_CHAIN_SPEC.md §3-§5 and confirm each "
            "anchor matches the head it checkpoints (§A3). The server's verified/head_hash above "
            "reproduce byte-for-byte under the verifier."),
    }


# ── Public refusal-log surface (human-readable; distinct from the machine /decisions) ──────────
# Substrings that must NEVER appear in any key of the PUBLIC refusal payload (defense-in-depth: the
# log itself is risk/audit data, but a future producer field could leak a secret — fail-CLOSED by
# dropping any matching key from the public projection).
_REFUSAL_REDACT_KEY_SUBSTRINGS = ("secret", "token", "key", "pat", "wallet", "address", "private")


def _redact_public(obj):
    """Recursively drop any dict key whose lowercased name contains a denylisted substring.

    Defense-in-depth over the public refusal projection: the human-readable feed is built from a
    fixed, audited set of fields, but this guard guarantees that even if an upstream field were
    renamed to carry a secret/token/key/pat/raw-wallet-address it can never reach the public payload.
    Lists/dicts are walked; scalars pass through unchanged. PURE."""
    if isinstance(obj, dict):
        return {
            k: _redact_public(v)
            for k, v in obj.items()
            if not any(s in str(k).lower() for s in _REFUSAL_REDACT_KEY_SUBSTRINGS)
        }
    if isinstance(obj, list):
        return [_redact_public(v) for v in obj]
    return obj


@router.get("/api/rates-desk/refusals")
def get_rates_desk_refusals(limit: int = Query(default=50, ge=1, le=500)):
    """PUBLIC, human-readable REFUSAL LOG — the declined-trades-with-reasons surface no competitor
    publishes. Distinct from the machine /api/rates-desk/decisions: this composes the hashed decision
    log with the STATIC audited refusal_explain map and the live chain verification.

    Each decision carries a plain-English + plain-Russian rationale whose every number is traceable
    to the row's own hashed YieldDecomposition (re-derivable via docs/PROOF_CHAIN_SPEC.md). Most-
    recent-first. Read-only, graceful, fail-CLOSED: a missing log yields an empty list with
    chain.verified=false, NEVER a 500. REDACTED: no secret/token/key/pat/raw-wallet field can appear;
    sizes are labeled advisory_size_usd (never raw size implying real capital)."""
    path = (data_dir() / "rates_desk" / "decision_log.jsonl")
    rows: list = []
    read_ok = False
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                parsed = parse_log_line(ln, corrupt_marker=_CORRUPT)
                rows.append(_CORRUPT_ROW if parsed is _CORRUPT else parsed)
            read_ok = True
        except OSError as e:
            log.warning(f"rates-desk refusals: decision log read failed: {e}")

    # Verify the WHOLE chain (tamper-evidence) before projecting any subset.
    chain = _verify_decision_log(rows)
    chain_badge = {
        "verified": bool(chain["valid"]),
        "head_hash": chain["head_hash"],
        "chain_length": chain["length"],
        "broken_at": chain["broken_at"],
        "spec": "docs/PROOF_CHAIN_SPEC.md",
    }
    # fail-CLOSED: if we never managed to read an existing log, report unverified explicitly.
    if path.exists() and not read_ok:
        chain_badge["verified"] = False

    counts = {"ENTRY": 0, "REFUSAL": 0}
    for r in rows:
        if isinstance(r, dict):
            k = r.get("kind")
            if k in counts:
                counts[k] += 1

    try:
        from spa_core.strategy_lab.rates_desk import refusal_explain
    except Exception as e:  # noqa: BLE001 — fail-CLOSED if the explain layer is unavailable
        log.warning(f"rates-desk refusals: refusal_explain import failed: {e}")
        return {
            "generated_at": now(),
            "model": "rates_desk_public_refusal_log",
            "chain": {**chain_badge, "verified": False},
            "counts": counts,
            "decisions": [],
        }

    # Most-recent-first projection, bounded by limit. Skip corrupt rows (they already failed the
    # chain check above → surfaced via chain.verified=false).
    decisions = []
    for r in reversed(rows):
        if len(decisions) >= limit:
            break
        if not isinstance(r, dict) or r.get("__corrupt__"):
            continue
        ex = refusal_explain.explain(r)
        decisions.append({
            "seq": r.get("seq"),
            "as_of": r.get("as_of"),
            "underlying": ex["underlying"],
            "shape": r.get("shape"),
            "kind": r.get("kind"),
            "headline": ex["headline"],
            "plain_en": ex["plain_en"],
            "plain_ru": ex["plain_ru"],
            "structural_reason": ex["structural_reason"],
            "drivers": ex["drivers"],
            "net_edge": r.get("net_edge"),
            "advisory_size_usd": ex["advisory_size_usd"],
            "proof_hash": r.get("proof_hash"),
            "entry_hash": r.get("entry_hash"),
            "prev_hash": r.get("prev_hash"),
        })

    payload = {
        "generated_at": now(),
        "model": "rates_desk_public_refusal_log",
        "chain": chain_badge,
        "counts": counts,
        "decisions": decisions,
        "reproduce": _reproduce_block(
            ["decision_log.jsonl"],
            "Every refusal's cited numbers live inside the hashed payload; re-derive entry_hash per "
            "PROOF_CHAIN_SPEC.md §3 to confirm no explanation number was back-fitted."),
    }
    # Defense-in-depth redaction over the entire public projection.
    return _redact_public(payload)


@router.get("/api/rates-desk/exit-nav")
def get_rates_desk_exit_nav():
    """Rates-Desk LIQUIDATION-NAV-BY-SIZE — the per-ticket exit schedule for the desk's open book.

    Serves data/rates_desk/exit_nav.json VERBATIM (built by the deterministic exit_nav engine): for
    each liquidation ticket ($100k/$250k/$1M/$5M/$10M) the CONSERVATIVE LOWER-BOUND net proceeds,
    price impact, haircut, and time-to-exit against the SINGLE-market contemporaneous Pendle PT depth.
    Read-only, graceful, fail-CLOSED: a missing/corrupt file yields an empty FLAGGED schedule with
    as_of=null, NEVER a 500. is_advisory is ALWAYS true.
    """
    _meta = backtest_meta(
        basis="conservative LOWER BOUND (constant-product L/(L+S)) on forced-unwind proceeds from "
              "single-market contemporaneous Pendle PT exit liquidity; NOT realized exits, NOT a "
              "precise execution model — tied to the Oct-2025 §9 exit-liquidity stress validation",
        period="current schedule (see as_of)",
    )
    raw = read_state("rates_desk/exit_nav.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "constant_product_amm_conservative_lower_bound",
            "as_of": None,
            "depth_usd": None,
            "book": None,
            "schedule": [],
            "illustrative": None,
            "flagged": True,
            "flag_reason": "exit_nav_unavailable",
            "is_advisory": True,
            "validation_ref": "docs/RATES_DESK_VALIDATION.md#exit-liquidity (Oct-2025 stress)",
            "meta": _meta,
            "reproduce": _reproduce_block(
                ["exit_nav.json"],
                "Each schedule row's proof_hash is reproducible per PROOF_CHAIN_SPEC.md §6 over the "
                "row's published inputs (live + illustrative + portfolio sections)."),
        }
    raw.setdefault("is_advisory", True)
    raw.setdefault("meta", _meta)
    raw.setdefault("reproduce", _reproduce_block(
        ["exit_nav.json"],
        "Each schedule row's proof_hash is reproducible per PROOF_CHAIN_SPEC.md §6 over the row's "
        "published inputs (live + illustrative + portfolio sections)."))
    # fail-CLOSED: a corrupt exit-nav file carrying a NaN/inf must not crash the serializer.
    return scrub_nonfinite(raw)


def _capacity_reproduce() -> dict:
    """Honest reproduce block for capacity — it is DETERMINISTIC ARITHMETIC (not a hash-chain),
    so it teaches re-derivation by re-running the aggregator, not by verify_spa hashing."""
    return {
        "deterministic": True,
        "method": "pure arithmetic over per-family (deployable_usd, net_apy_pct, floor_pct); "
                  "combined_deployable = naive_sum − correlation_haircut (both recorded); "
                  "above_floor_usd_per_yr = deployable · max(0, net_apy − RWA_floor)/100",
        "rerun": "python3 -m spa_core.strategy_lab.portfolio_capacity",
        "source": "data/rates_desk/portfolio_capacity.json",
        "doc": "docs/STRUCTURAL_DESK.md (combined portfolio-capacity section)",
    }


@router.get("/api/rates-desk/capacity")
def get_rates_desk_capacity():
    """Rates-Desk N-BOOK CAPACITY — the honest scale story: how much above-floor $/yr the desk's
    gated-carry book can realistically produce, and the GAP to the $10M thesis.

    Serves data/rates_desk/portfolio_capacity.json VERBATIM (built by the deterministic
    spa_core.strategy_lab.portfolio_capacity aggregator): per-family deployable capacity aggregated
    with an EXPLICIT correlation haircut for shared exit-liquidity (real desks share rails → the
    combined book is LESS than the naive sum, and BOTH the naive sum and the haircut are recorded),
    the resulting dollars_above_floor_per_yr, n_fundable_books, books_needed_for_10m, and the honest
    gap_to_10m. This is the machine-checkable mitigation for the #1 risk (the edge is unproven at
    fundable scale) — a number a diligence reviewer can reproduce, not a marketing claim. Read-only,
    graceful, fail-CLOSED: a missing/corrupt file yields a flagged empty payload with
    generated_at=null, NEVER a 500. is_advisory is ALWAYS true (no real capital; paper model only).
    """
    _meta = backtest_meta(
        basis="deterministic aggregate of per-family deployable capacity with an EXPLICIT correlation "
              "haircut on shared-venue exit liquidity (combined = naive_sum − haircut, both recorded); "
              "PT-carry depth is typically the binding constraint — see docs/STRUCTURAL_DESK.md",
        period="current model (see window / generated_at)",
    )
    raw = read_state("rates_desk/portfolio_capacity.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "portfolio_capacity_correlation_haircut",
            "total_deployable_usd": None,
            "dollars_above_floor_per_yr": None,
            "n_fundable_books": None,
            "books_needed_for_10m": None,
            "gap_to_10m_usd": None,
            "pct_of_10m_target": None,
            "books": [],
            "flagged": True,
            "flag_reason": "portfolio_capacity_unavailable",
            "is_advisory": True,
            "meta": _meta,
            "reproduce": _capacity_reproduce(),
        }
    raw.setdefault("is_advisory", True)
    raw.setdefault("meta", _meta)
    raw.setdefault("reproduce", _capacity_reproduce())
    # Defensive units annotation (endpoint-injected, NOT from the aggregator): the aggregator
    # stores `pct_of_10m_target` in PERCENT — 0.6478 means 0.65% of the $10M/yr target, NOT a
    # 0-1 fraction (64.78%). A naive machine parse of the bare number could overstate the desk
    # 100×, so we ship an explicit units map (and the dollar/gap fields + verbatim `note` remain
    # the unambiguous source). Never overstate: this exists only to make misreading impossible.
    raw.setdefault("field_units", {
        "pct_of_10m_target": "PERCENT — e.g. 0.65 means 0.65% of the $10M/yr target "
                             "(= dollars_above_floor_per_yr / target_above_floor_per_yr_usd × 100); NOT a 0-1 fraction",
        "dollars_above_floor_per_yr": "USD/yr of carry above the RWA floor",
        "target_above_floor_per_yr_usd": "USD/yr target (the $10M thesis)",
        "gap_to_10m_usd": "USD/yr shortfall to the target",
    })
    # fail-CLOSED: a corrupt capacity file carrying a NaN/inf must not crash the serializer.
    return scrub_nonfinite(raw)


@router.get("/api/rates-desk/n-book-capacity")
def get_rates_desk_n_book_capacity():
    """Rates-Desk N-BOOK SCALE CURVE — the finer-grained companion to /capacity: how above-floor $/yr
    grows as gated-carry BOOK-COUNT increases (distinct maturities/venues), with same-rail books haircut.

    Serves data/rates_desk/n_book_capacity.json VERBATIM (built by the deterministic
    spa_core.strategy_lab.rates_desk.n_book_capacity aggregator). It composes the honest per-book
    venue-depth curve with the single-pool APY→AUM compression model, so the "edge is a $100k/$250k
    artifact" objection becomes a MEASURED curve: above-floor $/yr plateaus because same-rail books share
    pool depth — the ceiling is set by the number of DISTINCT deep rails, not by stacking more books. This
    neither invents new depth nor asserts scale the pools do not support. Read-only, graceful, fail-CLOSED:
    a missing/corrupt file yields a flagged empty payload with generated_at=null, NEVER a 500.
    is_advisory is ALWAYS true (paper model only; never gates, never moves capital)."""
    _meta = backtest_meta(
        basis="deterministic composition of venue-expansion per-book deployable depth (correlation "
              "haircut applied) with the capacity.py single-pool APY→AUM compression curve; above-floor "
              "$/yr per rail cluster summed across distinct rails — see docs/STRUCTURAL_DESK.md",
        period="current model (see generated_at)",
    )
    _repro = {
        "deterministic": True,
        "rerun": "python3 -m spa_core.strategy_lab.rates_desk.n_book_capacity",
        "source": "data/rates_desk/n_book_capacity.json",
        "inputs": ["data/rates_desk/capacity.json (compression)",
                   "venue_expansion.live_curve (per-book depth + rail)"],
        "doc": "docs/STRUCTURAL_DESK.md (N-book capacity section)",
    }
    raw = read_state("rates_desk/n_book_capacity.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "n_book_capacity_aggregator",
            "curve": [],
            "plateau_above_floor_usd_per_yr": None,
            "n_books_total": None,
            "n_distinct_rails": None,
            "flagged": True,
            "flag_reason": "n_book_capacity_unavailable",
            "is_advisory": True,
            "meta": _meta,
            "reproduce": _repro,
        }
    raw.setdefault("is_advisory", True)
    raw.setdefault("meta", _meta)
    raw.setdefault("reproduce", _repro)
    raw.setdefault("field_units", {
        "above_floor_usd_per_yr": "USD/yr of carry above the RWA floor at that book-count",
        "deployable_usd": "USD honest (haircut-adjusted) deployable across the first n books",
        "blended_above_floor_pct": "PERCENTAGE POINTS above floor, blended over the deployed book",
        "marginal_value_of_last_book_usd_per_yr": "USD/yr the LAST book added contributes (≈0 = rail-saturated)",
    })
    return scrub_nonfinite(raw)


@router.get("/api/rates-desk/anchors")
def get_rates_desk_anchors(limit: int = Query(default=50, ge=1, le=500)):
    """Rates-Desk CROSS-EVICTION immutability anchors — data/rates_desk/anchors.jsonl.

    The append-only, monotonic ledger of {ts, seq, head_hash, chain_length} checkpoints over the
    public decision chain's head (PROOF_CHAIN_SPEC.md §5 anchoring caveat / A3). Each anchor is a
    time-stamped external commitment that the chain at that length hashed to that head — so even after
    the 2000-row public window evicts old rows, a third party can prove no in-window history was
    rewritten between two checkpoints. Read-only, graceful, fail-CLOSED: an absent ledger yields an
    empty, vacuously-valid result, NEVER a 500. Verifiable WITHOUT our code via scripts/verify_spa.py.
    """
    path = (data_dir() / "rates_desk" / "anchors.jsonl")
    rows: list = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                parsed = parse_log_line(ln, corrupt_marker=_CORRUPT)
                rows.append(_CORRUPT_ROW if parsed is _CORRUPT else parsed)
        except OSError as e:
            log.warning(f"rates-desk anchors read failed: {e}")

    badge = {"valid": True, "length": len(rows), "broken_at": None, "latest_matches_head": None}
    try:
        from spa_core.strategy_lab.rates_desk import anchors as _anchors
        badge = _anchors.verify_anchors()
    except Exception as e:  # noqa: BLE001 — fail-CLOSED, never 500
        log.warning(f"rates-desk anchors verify failed: {e}")
        badge = {"valid": False, "length": len(rows), "broken_at": None, "latest_matches_head": None}

    return {
        "generated_at": now(),
        "model": "rates_desk_anchor_ledger",
        "n_anchors": len(rows),
        "verified": bool(badge["valid"]),
        "broken_at": badge["broken_at"],
        "latest_matches_head": badge["latest_matches_head"],
        "anchors": rows[-limit:],
        "reproduce": _reproduce_block(
            ["decision_log.jsonl", "anchors.jsonl"],
            "Append-only + monotonic; the anchor whose chain_length == the re-derived decision-chain "
            "length must carry that exact head_hash (PROOF_CHAIN_SPEC.md §5 anchoring caveat)."),
    }


# ── FULL-CHAIN download surface (audit finding #1) ────────────────────────────────────────────────
# The /proof and /decisions and /anchors views are CAPPED (last_n≤200, limit≤500) — fine for a human
# glance, but a stranger who wants to RE-DERIVE the head with scripts/verify_spa.py needs EVERY byte of
# the underlying file (the chain is 500+ rows). These endpoints serve the COMPLETE public proof
# artifacts VERBATIM (raw bytes, NO cap, NO reformat) so an outsider can curl them onto a clean machine
# and run the zero-dependency verifier end-to-end. Read-only, fail-CLOSED: an unknown surface or a
# missing file is a 404 (never a fabricated/empty success). NO secret/state ever lives in these files.
#
# Each surface maps to the EXACT public file scripts/verify_spa.py consumes (and PROOF_CHAIN_SPEC.md
# documents). Served as text/plain so the bytes are delivered unchanged (JSONL files are not single
# JSON documents; a JSON response would reframe them).
_FULL_CHAIN_FILES = {
    "decision_log": "rates_desk/decision_log.jsonl",   # (A) the tamper-evident decision chain
    "exit_nav": "rates_desk/exit_nav.json",            # (B) per-row exit-NAV proof_hash document
    "anchors": "rates_desk/anchors.jsonl",             # (C) cross-eviction head anchors
    "equity_track": "rates_desk/equity_track.jsonl",   # (D) evidenced equity / go-live track
    "tournament": "tournament/decision_log.jsonl",     # (E) tournament ranking chain
    "nav_proof": "rwa_backstop/nav_proof.jsonl",       # (F) RWA-backstop NAV forward proof
    "sleeve": "rates_desk/paper/rates_desk_fixed_carry_series_proof.jsonl",  # (G) sleeve fwd-series
}


@router.get("/api/rates-desk/full-chain", response_class=PlainTextResponse)
def list_full_chain_surfaces():
    """List the COMPLETE public proof files a stranger can download to reproduce every head.

    The download index for audit finding #1: each `surface` here has a `/api/rates-desk/full-chain/
    {surface}` endpoint that serves its ENTIRE underlying file VERBATIM (no cap) — so an outsider curls
    them, drops them under a clean `data/` tree, runs `python3 verify_spa.py data/`, and reproduces the
    same head_hash this API reports. Read-only; never includes any secret/state file."""
    import json as _json
    base = data_dir()
    surfaces = []
    for key, rel in _FULL_CHAIN_FILES.items():
        p = base / rel
        surfaces.append({
            "surface": key,
            "file": rel,
            "download": f"/api/rates-desk/full-chain/{key}",
            "present": p.exists(),
        })
    return _json.dumps({
        "generated_at": now(),
        "model": "rates_desk_full_chain_index",
        "note": "Each download endpoint serves the COMPLETE file verbatim (no last_n/limit cap) so a "
                "third party can re-derive every head with scripts/verify_spa.py. "
                "Recipe: curl each → save under data/<file> → python3 verify_spa.py data/",
        "spec": "docs/PROOF_CHAIN_SPEC.md",
        "verifier": "scripts/verify_spa.py (zero-dependency, no spa_core import)",
        "surfaces": surfaces,
    }, indent=2)


@router.get("/api/rates-desk/full-chain/{surface}", response_class=PlainTextResponse)
def get_full_chain(surface: str):
    """Serve ONE complete public proof file VERBATIM — the full, uncapped chain for reproduction.

    The owner-independent reproducibility path (audit finding #1): unlike /proof (last_n≤200) or
    /decisions (limit≤500), this streams EVERY byte of the underlying artifact unmodified, so a
    skeptic can pull the WHOLE chain and re-derive the head locally with scripts/verify_spa.py.

    Read-only, fail-CLOSED:
      • an UNKNOWN surface → 404 (never a fabricated body);
      • a KNOWN surface whose file is ABSENT → 404 (we do not invent an empty success — absence is a
        real, honest condition the verifier should see, not a silent pass).
    Bytes are returned exactly as on disk (text/plain), so the verifier hashes the same bytes we do."""
    from fastapi import HTTPException
    rel = _FULL_CHAIN_FILES.get(surface)
    if rel is None:
        raise HTTPException(status_code=404, detail={
            "error": "unknown_surface",
            "surface": surface,
            "known_surfaces": sorted(_FULL_CHAIN_FILES),
            "index": "/api/rates-desk/full-chain",
        })
    path = data_dir() / rel
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail={
            "error": "surface_file_absent",
            "surface": surface,
            "file": rel,
            "note": "fail-CLOSED: the file does not exist yet; no fabricated/empty body is served.",
        })
    return PlainTextResponse(content=raw, media_type="text/plain; charset=utf-8")


@router.get("/api/rates-desk/track")
def get_rates_desk_track():
    """Rates-Desk LIVE paper forward-track — the validated FixedCarry sleeve, accruing.

    Serves data/rates_desk/paper/ (status.json + {sleeve}_series.json). Read-only, graceful,
    fail-CLOSED: empty track when no track exists yet. is_advisory is ALWAYS true.
    """
    status = read_state("rates_desk/paper/status.json", {})
    series_doc = read_state("rates_desk/paper/rates_desk_fixed_carry_series.json", {})

    sleeve = status.get("sleeve", {}) if isinstance(status, dict) else {}
    sleeve_id = sleeve.get("id") or (series_doc.get("id") if isinstance(series_doc, dict) else None) \
        or "rates_desk_fixed_carry"

    raw_series = series_doc.get("series", []) if isinstance(series_doc, dict) else []
    daily_series = []
    for pt in raw_series:
        if not isinstance(pt, dict):
            continue
        eq = pt.get("equity_usd")
        daily_series.append({
            "date": pt.get("date"),
            "equity": eq,
            "nav": eq,
            "net_apy_pct": pt.get("net_apy_pct"),
        })

    started_at = daily_series[0]["date"] if daily_series else None
    days = len(daily_series)

    current_equity = None
    cumulative_return_pct = None
    if daily_series:
        first_eq = daily_series[0].get("equity")
        last_eq = daily_series[-1].get("equity")
        current_equity = last_eq if last_eq is not None else sleeve.get("equity_usd")
        if isinstance(first_eq, (int, float)) and first_eq and isinstance(last_eq, (int, float)):
            cumulative_return_pct = round((last_eq / first_eq - 1.0) * 100.0, 6)
    else:
        current_equity = sleeve.get("equity_usd")

    # fail-CLOSED: derived fields read from a possibly-corrupt series file → scrub NaN/inf.
    return scrub_nonfinite({
        "generated_at": now(),
        "model": "rates_desk_paper_track",
        "sleeve_id": sleeve_id,
        "name": sleeve.get("name"),
        "started_at": started_at,
        "days": days,
        "current_equity": current_equity,
        "cumulative_return_pct": cumulative_return_pct,
        "net_apy_pct": sleeve.get("net_apy_pct"),
        "open_books": sleeve.get("open_books"),
        "closed_books": sleeve.get("closed_books"),
        "last_tick": sleeve.get("last_tick"),
        "gap": status.get("gap") if isinstance(status, dict) else None,
        "daily_series": daily_series,
        "is_advisory": True,
        "meta": backtest_meta(
            basis="deep Pendle PT history 2024-01→2026-06, total-capital basis, "
                  "capacity-constrained; advisory paper forward-track, NOT real capital",
            period="rates-desk paper forward-track (see started_at/days)",
        ),
    })
