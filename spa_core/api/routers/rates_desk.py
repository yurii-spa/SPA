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

from spa_core.api._shared import backtest_meta, data_dir, now, read_state

log = logging.getLogger("spa.api")

router = APIRouter(tags=["strategy_lab"])


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
    return raw


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
        return scan
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
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
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


# Payload keys carried by every decision_log mirror row that are NOT part of the
# hash-covered decision payload (they are the chain-linkage envelope).
_PROOF_ENVELOPE_KEYS = ("seq", "ts", "entry_hash", "prev_hash")
_PROOF_EVENT_TYPE = "rates_desk_decision"


def _verify_decision_log(rows: list) -> dict:
    """Re-derive the hash over every public decision_log mirror row, fail-CLOSED — tamper-evidence.

    Each mirror row is ``{seq, ts, entry_hash, prev_hash, **decision_payload}``. We verify each
    row's INTRINSIC authenticity: every entry_hash must recompute via hash_chain.compute_entry_hash
    over the row's own payload + seq/ts/prev_hash. Returns
    {"valid", "length", "broken_at", "head_hash"}; an empty log is valid.
    """
    try:
        from spa_core.audit import hash_chain
    except Exception as e:  # noqa: BLE001 — fail-CLOSED if the integrity module is unavailable
        log.warning(f"rates-desk proof: hash_chain import failed: {e}")
        return {"valid": False, "length": len(rows), "broken_at": None, "head_hash": None}

    head_seq = None
    head_hash = None
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head_hash}
        seq = row.get("seq")
        ts = row.get("ts")
        prev_hash = row.get("prev_hash")
        entry_hash = row.get("entry_hash")
        payload = {k: v for k, v in row.items() if k not in _PROOF_ENVELOPE_KEYS}
        try:
            recomputed = hash_chain.compute_entry_hash(seq, ts, _PROOF_EVENT_TYPE, payload, prev_hash)
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED at this row
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head_hash}
        if recomputed != entry_hash:
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head_hash}
        if isinstance(seq, int) and (head_seq is None or seq > head_seq):
            head_seq = seq
            head_hash = entry_hash
    return {"valid": True, "length": len(rows), "broken_at": None, "head_hash": head_hash}


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
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    rows.append({"__corrupt__": True})
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

    return {
        "generated_at": now(),
        "model": "rates_desk_proof_chain",
        "chain_length": result["length"],
        "head_hash": result["head_hash"],
        "verified": result["valid"],
        "broken_at": result["broken_at"],
        "counts": counts,
        "last_n_decisions": last,
    }


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
            "flagged": True,
            "flag_reason": "exit_nav_unavailable",
            "is_advisory": True,
            "validation_ref": "docs/RATES_DESK_VALIDATION.md#exit-liquidity (Oct-2025 stress)",
            "meta": _meta,
        }
    raw.setdefault("is_advisory", True)
    raw.setdefault("meta", _meta)
    return raw


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

    return {
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
    }
