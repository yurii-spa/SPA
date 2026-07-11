"""Swarm router (block 6 SURFACE) — the public, read-only surface of the SPA Swarm.

Charter: docs/SWARM_ARCHITECTURE.md. Serves the swarm's own status artifacts VERBATIM (the swarm
agents are the producers; this router computes NOTHING):

    /api/swarm/guardian  — L2 position guardians (per-book ARMED/DERISKED, guarded-vs-raw, events)
    /api/swarm/regime    — L1 funding-regime classifier (GREEN/YELLOW/RED/UNKNOWN carry weather)
    /api/swarm/blend     — L3 cross-desk blend forward paper portfolio (idea #3, 25/50/25)
    /api/swarm/brain     — L3 dynamic-leverage recommendations (refusal-first; null = refusal)
    /api/swarm/health    — L4 immune layer (organ freshness / contracts / proof tamper-check)

GUARDRAILS: every payload is stamped advisory / paper-only / outside_riskpolicy — the swarm
watches and recommends; it NEVER allocates and never touches the go-live track. FAIL-CLOSED:
a missing/corrupt artifact → 200 with an honest "unavailable" envelope, never a 500, never a
fabricated number. Read-only; stdlib-only on the serve path. LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from fastapi import APIRouter

from spa_core.api._shared import read_state, scrub_nonfinite

router = APIRouter(tags=["swarm"])

_ADVISORY_NOTE = (
    "SPA Swarm surface — ADVISORY, paper-only, outside RiskPolicy v1.0. The swarm monitors the "
    "paper books and the market and RECOMMENDS de-risk/sizing; it never moves capital and never "
    "touches the go-live track. null leverage = REFUSAL (read as zero exposure). Charter: "
    "docs/SWARM_ARCHITECTURE.md."
)

_ORGANS = {
    "guardian": ("swarm/guardian_forward.json", "swarm.guardian_forward",
                 "L2 position guardians over the aggressive_lab forward paper track"),
    "regime": ("swarm/funding_regime.json", "swarm.funding_regime",
               "L1 GREEN/YELLOW/RED carry-regime classifier (5-venue median funding)"),
    "blend": ("swarm/blend_forward.json", "swarm.blend_forward",
              "L3 forward 3-desk blend paper portfolio (validated idea #3, 25/50/25)"),
    "brain": ("swarm/leverage_brain.json", "swarm.leverage_brain",
              "L3 dynamic-leverage recommendations (refusal-first)"),
    "health": ("swarm/swarm_health.json", "swarm.swarm_health",
               "L4 immune layer — monitors the monitors"),
}


def _serve(organ: str) -> dict:
    rel_path, model, desc = _ORGANS[organ]
    raw = read_state(rel_path, {})
    if not raw or not isinstance(raw, dict):
        return {
            "available": False,
            "model": model,
            "unavailable_reason": f"{rel_path} not produced yet — the swarm agent for this organ "
                                  "has not run (or its artifact is unreadable)",
            "advisory": True,
            "outside_riskpolicy": True,
            "live_eligible": False,
            "note": _ADVISORY_NOTE,
            "description": desc,
        }
    out = dict(raw)
    out["available"] = True
    out.setdefault("model", model)
    # Authoritative stamps — the surface can never present the swarm as live-allocating.
    out["advisory"] = True
    out["outside_riskpolicy"] = True
    out["live_eligible"] = False
    out["note"] = _ADVISORY_NOTE
    return scrub_nonfinite(out)


@router.get("/api/swarm/guardian")
def get_swarm_guardian():
    """L2 position guardians — data/swarm/guardian_forward.json VERBATIM (fail-closed)."""
    return _serve("guardian")


@router.get("/api/swarm/regime")
def get_swarm_regime():
    """L1 funding-regime — data/swarm/funding_regime.json VERBATIM (fail-closed). Consumers MUST
    treat UNKNOWN (and unavailable) as not-GREEN."""
    return _serve("regime")


@router.get("/api/swarm/blend")
def get_swarm_blend():
    """L3 cross-desk blend forward — data/swarm/blend_forward.json VERBATIM (fail-closed)."""
    return _serve("blend")


@router.get("/api/swarm/brain")
def get_swarm_brain():
    """L3 leverage recommendations — data/swarm/leverage_brain.json VERBATIM (fail-closed).
    null leverage_reco = REFUSAL: any consumer must read it as zero exposure."""
    return _serve("brain")


@router.get("/api/swarm/health")
def get_swarm_health():
    """L4 immune layer — data/swarm/swarm_health.json VERBATIM (fail-closed)."""
    return _serve("health")
