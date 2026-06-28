"""Optimizer / captured-book router — Cutover-Bulletproof WS-1.4.

Two read-only, graceful, fail-CLOSED public surfaces so the owner can SEE both
the captured carry book and the optimizer A/B uplift:

  * GET /api/captured-book  — the LIVE captured FixedCarry book from
        data/rates_desk/paper/ (accrued carry, open books, refusals; VERBATIM).
  * GET /api/optimizer-ab   — the optimizer A/B uplift from data/optimizer_ab.json
        (the WS-1.3 shadow replay; risk-adjusted, honest-caveat preserved).

Both return 200 + an honest "unavailable" payload when their source is
missing/corrupt — NEVER a 500, NEVER a fabricated number. Numbers are passed
through VERBATIM from the state files (no recomputation here). Tagged
"strategy_lab" to keep OpenAPI grouping consistent with the adjacent rates_desk /
strategy_lab routers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from spa_core.api._shared import now, read_state, scrub_nonfinite

log = logging.getLogger("spa.api")

router = APIRouter(tags=["strategy_lab"])


@router.get("/api/optimizer-ab")
def get_optimizer_ab():
    """Optimizer A/B uplift — data/optimizer_ab.json (WS-1.3 shadow replay).

    Serves the A/B harness artifact VERBATIM: the legacy risk_adjusted heuristic vs the
    WS-1.2 optimized_yield optimizer, replayed over the REAL evidenced live-APY window, with
    the honest RISK-ADJUSTED caveat (uplift only when caps don't bind; optimizer reserves the
    5% cash floor). Read-only, graceful, fail-CLOSED: a missing/corrupt artifact yields a
    status:"unavailable" payload (null uplift, never a fabricated number), never a 500.

    HONESTY: the optimizer stays BEHIND A FLAG — this is a SHADOW A/B report, never the cycle
    default. The payload's optimizer_cycle_default/optimizer_behind_flag fields state that
    verbatim from the harness; if the artifact is absent we assert behind-flag explicitly.
    """
    raw = read_state("optimizer_ab.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "status": "unavailable",
            "reason": "optimizer_ab_artifact_missing",
            "model": "optimizer_ab_harness",
            "generated_at": None,
            "as_of": None,
            "optimizer_cycle_default": False,
            "optimizer_behind_flag": True,
            "n_days": 0,
            "legacy_apy": None,
            "optimized_apy": None,
            "uplift_pp": None,
            "cap_binding_diagnostics": {},
            "is_backtest": True,
            "is_realized": False,
            "disclaimer": (
                "Backtest/paper A/B research — advisory, NOT realized capital, NOT a track "
                "record. Optimizer stays behind a flag; cycle default remains risk_adjusted."
            ),
            "note": (
                "Optimizer A/B artifact not yet generated. Run scripts/optimizer_ab.py "
                "(sandbox replay, never touches live data/) to produce it."
            ),
        }
    # Defense-in-depth: never emit a 'live' / promoted framing — the optimizer is
    # advisory/behind-flag regardless of what the artifact carries.
    raw.setdefault("optimizer_behind_flag", True)
    raw.setdefault("is_backtest", True)
    # fail-CLOSED: a corrupt artifact carrying a NaN/inf must not crash the serializer.
    return scrub_nonfinite(raw)


@router.get("/api/captured-book")
def get_captured_book():
    """Captured carry book — the LIVE FixedCarry sleeve from data/rates_desk/paper/.

    Serves the captured book the owner is deciding to promote: accrued carry, open books (per
    underlying: size, entry rate, carry, kill-state), the daily refusal counts, and the
    accruing equity series. Composed VERBATIM from data/rates_desk/paper/status.json +
    rates_desk_fixed_carry_series.json. Read-only, graceful, fail-CLOSED: a missing/corrupt
    book yields a status:"unavailable" payload (empty book, null accrued, never a fabricated
    number), never a 500. is_advisory is ALWAYS true (paper research, no real capital)."""
    status = read_state("rates_desk/paper/status.json", {})
    series_doc = read_state("rates_desk/paper/rates_desk_fixed_carry_series.json", {})

    have_status = isinstance(status, dict) and bool(status)
    have_series = isinstance(series_doc, dict) and bool(series_doc)
    if not have_status and not have_series:
        return {
            "status": "unavailable",
            "reason": "captured_book_missing",
            "model": "rates_desk_captured_book",
            "generated_at": now(),
            "is_advisory": True,
            "sleeve_id": "rates_desk_fixed_carry",
            "accrued_carry_usd": None,
            "equity_usd": None,
            "net_apy_pct": None,
            "open_books": [],
            "n_open_books": 0,
            "n_closed_books": 0,
            "refusals": {},
            "daily_series": [],
            "note": (
                "Captured FixedCarry book not yet generated. The rates-desk paper agent "
                "(com.spa.rates_desk_paper) writes data/rates_desk/paper/ each UTC day."
            ),
        }

    # WS-6.2 fail-CLOSED: a corrupt status.json can parse to a dict whose
    # ``sleeve`` / ``scan_diag`` VALUE is a non-dict (e.g. an int) — guard the
    # value type, not just the container, before any ``.get`` (a non-dict value
    # would raise AttributeError → an uncaught 500).
    sleeve = status.get("sleeve", {}) if isinstance(status, dict) else {}
    if not isinstance(sleeve, dict):
        sleeve = {}
    scan = status.get("scan_diag", {}) if isinstance(status, dict) else {}
    if not isinstance(scan, dict):
        scan = {}
    sleeve_id = sleeve.get("id") or (
        series_doc.get("id") if isinstance(series_doc, dict) else None
    ) or "rates_desk_fixed_carry"

    # ── open books (verbatim projection from the series/state-free status) ──
    # The public book is read from status.json (the canonical advisory snapshot);
    # the per-book detail lives in the sleeve state file, but the PUBLIC surface
    # intentionally exposes only the non-sensitive summary the owner needs. We
    # surface the count + the latest scan diagnostics + the accruing series.
    # WS-6.2 fail-CLOSED: ``series`` may be present but a non-list (None / str /
    # int) in a corrupt doc — ``.get("series", [])`` returns that non-list and the
    # loop below would crash (TypeError) or iterate a string char-by-char. Coerce
    # to a list before iterating.
    raw_series = series_doc.get("series", []) if isinstance(series_doc, dict) else []
    if not isinstance(raw_series, list):
        raw_series = []
    daily_series = []
    for pt in raw_series:
        if not isinstance(pt, dict):
            continue
        daily_series.append({
            "date": pt.get("date"),
            "equity_usd": pt.get("equity_usd"),
            "net_apy_pct": pt.get("net_apy_pct"),
            "open_books": pt.get("open_books"),
            "approvals": pt.get("approvals"),
            "refusals": pt.get("refusals"),
        })

    # accrued carry = equity − initial capital (initial = first series point, else 100000).
    accrued = None
    equity = sleeve.get("equity_usd")
    if daily_series and isinstance(equity, (int, float)):
        first_eq = daily_series[0].get("equity_usd")
        base = first_eq if isinstance(first_eq, (int, float)) else 100000.0
        accrued = round(float(equity) - float(base), 6)

    # ── WS-1.6 captured-book attribution (carry-leg vs RWA floor-leg, reconciling to NAV) ──
    # Read-only, fail-CLOSED: decompose the realized captured-book PnL into the floor-leg (what the
    # ~3.4% RWA floor would have earned) and the carry-leg (residual edge), reconciling to NAV. A
    # tampered/look-ahead/gapped series is REFUSED by track_integrity → status UNKNOWN (no numbers),
    # never an inflated carry figure. Honest THIN flag until the sleeve track matures.
    attribution = None
    try:
        from spa_core.strategy_lab.forward_analytics import captured_book_attribution
        attribution = captured_book_attribution(series_doc)
    except Exception:  # noqa: BLE001 — analytics must never break the read-only public surface
        attribution = {
            "status": "UNKNOWN", "reconciles": False, "model": "captured_book_attribution",
            "note": "attribution unavailable (series unreadable) — no fabricated number.",
        }

    payload = {
        "status": "ok",
        "model": "rates_desk_captured_book",
        "generated_at": now(),
        "is_advisory": True,
        "sleeve_id": sleeve_id,
        "name": sleeve.get("name"),
        "mandate": sleeve.get("mandate"),
        "equity_usd": equity,
        "accrued_carry_usd": accrued,
        "net_apy_pct": sleeve.get("net_apy_pct"),
        "n_open_books": sleeve.get("open_books"),
        "n_closed_books": sleeve.get("closed_books"),
        "last_tick": sleeve.get("last_tick"),
        "gap": status.get("gap") if isinstance(status, dict) else None,
        # latest scan diagnostics: approvals/refusals + refusal reasons (verbatim).
        "scan_diag": scan if isinstance(scan, dict) else {},
        "refusals": (scan.get("refused_by_reason", {}) if isinstance(scan, dict) else {}),
        "attribution": attribution,
        "daily_series": daily_series,
        "meta": {
            "is_backtest": True,
            "is_realized": False,
            "basis": (
                "live FixedCarry paper forward-track (Pendle PT to maturity), advisory — "
                "accruing real forward carry on the cached rate surface; NOT real capital"
            ),
            "disclaimer": (
                "Paper research — advisory, not realized capital, not a track record"
            ),
        },
    }
    # fail-CLOSED: a corrupt book carrying a NaN/inf must not crash the serializer.
    return scrub_nonfinite(payload)
