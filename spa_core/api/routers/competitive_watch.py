"""Competitive-Watch router (WS-E Proof-of-Risk) — the Section-7 early-warning radar.

Surfaces data/competitive_watch.json: the deterministic, fail-CLOSED state of each
Section-7 watch-threshold (SAFE / WATCH / BREACHED) with honest manual-pending
labeling. Read-only, graceful: an absent/corrupt file yields an all-WATCH
fail-closed payload, NEVER a 500 and NEVER a fabricated competitor state.

OWNER-GATE: the PUBLIC page that NAMES competitors is owner-gated per the report.
This endpoint is INTERNAL-surfaceable (the payload carries public_naming_owner_gated
=true and is_internal_surface=true). The dashboard team should render the state
TABLE internally; do not expose competitor names publicly until the owner decides.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from spa_core.api._shared import now, read_state, scrub_nonfinite

log = logging.getLogger("spa.api")

router = APIRouter(tags=["competitive_watch"])

# Stable Section-7 threshold catalogue so the endpoint can render a COMPLETE,
# honest table even before the monitor has ever written its state file (every
# entry shown as fail-closed WATCH / manual_pending). Mirrors the coded checks in
# spa_core.monitoring.competitive_watch.SECTION7_THRESHOLDS.
_FALLBACK_SIGNAL_IDS = (
    "chaos_gauntlet_investor_exit_nav",
    "exponential_yo_exit_nav",
    "exponential_yo_refusal_log",
    "kraken_coinbase_risk_rationale",
)


def _empty_payload() -> dict:
    """Fail-CLOSED empty payload: every known threshold shown as WATCH/manual_pending."""
    try:
        from spa_core.monitoring.competitive_watch import SECTION7_THRESHOLDS, WATCH
        signals = [
            {
                "signal_id": t.signal_id,
                "category": t.category,
                "competitors": list(t.competitors),
                "description": t.description,
                "breach_meaning": t.breach_meaning,
                "state": WATCH,
                "as_of": None,
                "evidence": None,
                "source_url": None,
                "manual_pending": True,
                "note": "monitor has not run yet — fail-closed WATCH",
            }
            for t in SECTION7_THRESHOLDS
        ]
    except Exception as e:  # noqa: BLE001 — never 500; degrade to id-only stub
        log.warning(f"competitive-watch fallback catalogue unavailable: {e}")
        signals = [
            {"signal_id": sid, "state": "WATCH", "manual_pending": True,
             "note": "monitor has not run yet — fail-closed WATCH"}
            for sid in _FALLBACK_SIGNAL_IDS
        ]
    return {
        "schema": "spa.competitive_watch.v1",
        "model": "section7_watch_thresholds",
        "generated_at": None,
        "overall_state": "WATCH",
        "counts": {"SAFE": 0, "WATCH": len(signals), "BREACHED": 0},
        "n_signals": len(signals),
        "n_breached": 0,
        "breached_ids": [],
        "manual_pending_ids": sorted(s["signal_id"] for s in signals),
        "public_naming_owner_gated": True,
        "is_internal_surface": True,
        "fail_closed_note": (
            "No competitive_watch.json yet — fail-closed: every threshold WATCH, "
            "never a silent SAFE. Competitor states are never fabricated."
        ),
        "signals": signals,
    }


@router.get("/api/competitive-watch")
def get_competitive_watch():
    """Section-7 competitive watch-threshold radar — data/competitive_watch.json.

    INTERNAL surface (public competitor-naming is owner-gated). Read-only, graceful,
    fail-CLOSED: a missing/corrupt state file yields an all-WATCH payload, never a
    500 and never a fabricated competitor state. The state for each threshold is
    SAFE (sourced clear) / WATCH (unknown or manual-pending) / BREACHED (sourced).
    """
    raw = read_state("competitive_watch.json", {})
    # fail-CLOSED: require a dict with a LIST of signals; anything else (missing, corrupt,
    # wrong-typed signals) degrades to the all-WATCH fallback, never a fabricated state.
    if not raw or not isinstance(raw, dict) or not isinstance(raw.get("signals"), list) \
            or not raw.get("signals"):
        return _empty_payload()
    # Served VERBATIM; ensure the owner-gate flags are present even on older files.
    raw.setdefault("public_naming_owner_gated", True)
    raw.setdefault("is_internal_surface", True)
    raw.setdefault("served_at", now())
    # fail-CLOSED: a corrupt file carrying a NaN/inf must not crash the serializer.
    return scrub_nonfinite(raw)
