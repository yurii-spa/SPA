"""Red-team router — serves data/redteam_status.json (the standing adversarial harness verdict).

The "we red-team ourselves" claim is itself verifiable: the served status carries the anchored
``report_hash`` and the hash_chain anchor (seq / entry_hash) so a consumer re-derives the hash from
the verdict body and re-runs ``hash_chain.verify_chain()`` to confirm it.

Read-only, graceful, fail-CLOSED: a missing/corrupt status yields an explicit
``{"available": false}`` envelope (never a 500, never a fabricated PASS).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging

from fastapi import APIRouter

from spa_core.api._shared import read_state, scrub_nonfinite

log = logging.getLogger("spa.api")

router = APIRouter(tags=["redteam"])


@router.get("/api/redteam")
def get_redteam_status():
    """The latest standing red-team verdict — data/redteam_status.json, served VERBATIM.

    Fail-CLOSED: when the status file is absent or unparsable we return an explicit
    ``available: false`` envelope (NOT a fabricated pass), so a consumer/dashboard can render an
    honest "no red-team run yet" state rather than mistaking silence for safety.
    """
    raw = read_state("redteam_status.json", {})
    if not raw or not isinstance(raw, dict) or "verdict" not in raw:
        return {
            "available": False,
            "ok": None,
            "note": ("no red-team status published yet — run "
                     "`python3 -m spa_core.redteam.rotation` (or the rotation agent)"),
        }
    verdict = raw.get("verdict") or {}
    # surface the load-bearing fields at the top level for an easy dashboard read, then the full
    # verdict + the anchor (so the claim is independently verifiable).
    out = {
        "available": True,
        "ok": verdict.get("ok"),
        "surface": verdict.get("surface"),
        "scope": verdict.get("scope"),
        "n": verdict.get("n"),
        "n_caught": verdict.get("n_caught"),
        "n_failed": verdict.get("n_failed"),
        "live_data_untouched": verdict.get("live_data_untouched"),
        "ts": raw.get("ts"),
        "report_hash": raw.get("report_hash"),
        "anchor": raw.get("anchor"),
        "reproduce": raw.get("reproduce"),
        "verdict": verdict,
    }
    # fail-CLOSED against any non-finite number sneaking into a corrupt status (no serializer crash).
    return scrub_nonfinite(out)
