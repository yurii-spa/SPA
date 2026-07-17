"""AI Investment OS router — the public, read-only surface of the product-layer analysts (docs/08).

Serves each analyst's OWN advisory artifact VERBATIM (the analysts are the producers; this router computes
NOTHING):

    /api/investment-os                 index of analysts + availability
    /api/investment-os/stablecoin-yield  top conservative-tier stablecoin yields (risk-adjusted)
    /api/investment-os/market-regime     unified yield+funding regime view (most-cautious combined)
    /api/investment-os/reporting         evidenced track + day-30 review readiness

GUARDRAILS: every payload is ADVISORY / paper-only — the analysts observe and evidence-tag; they never
allocate and never touch the go-live track. FAIL-CLOSED: a missing/corrupt artifact → 200 with an honest
"unavailable" envelope, never a 500, never a fabricated number. Read-only; stdlib on the serve path.
LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from fastapi import APIRouter

from spa_core.api._shared import read_state

router = APIRouter(tags=["investment-os"])

_ADVISORY_NOTE = (
    "AI Investment OS surface — ADVISORY, paper/research only. The analysts observe the live feeds and "
    "the desk's own evidenced track and EVIDENCE-TAG (L0-L6) what they surface; they never allocate, "
    "never gate execution (the deterministic RiskPolicy is the only gate), and never touch the go-live "
    "track. UNKNOWN = refused (missing/stale feed), never a fabricated number. Design: docs/08."
)

# slug → (artifact file under data/, agent key, description)
_ANALYSTS = {
    "stablecoin-yield": ("investment_os/stablecoin_yield.json", "stablecoin_yield",
                         "Top conservative-tier (T1/T2) stablecoin yields by risk-adjusted APY; "
                         "exotic T3 excluded (refused-for-live)"),
    "market-regime": ("investment_os/market_regime.json", "market_regime",
                      "Unified yield-regime + funding-regime view; combined posture = most-cautious"),
    "reporting": ("investment_os/reporting.json", "reporting",
                  "The desk's OWN evidenced paper track + day-30 review readiness (L6)"),
    "red-team": ("investment_os/red_team.json", "red_team",
                 "Adversarial threat posture — can only RAISE concern, never approves; missing/stale "
                 "threat data → UNKNOWN_CAUTIOUS"),
}


def _serve(slug: str) -> dict:
    rel_path, agent, desc = _ANALYSTS[slug]
    raw = read_state(rel_path, {})
    if not raw or not isinstance(raw, dict):
        return {
            "available": False,
            "agent": agent,
            "unavailable_reason": f"{rel_path} not produced yet — the {agent} analyst has not run "
                                  "(or its artifact is unreadable)",
            "is_advisory": True,
            "live_eligible": False,
            "description": desc,
            "note": _ADVISORY_NOTE,
        }
    out = dict(raw)
    out["available"] = True
    out.setdefault("agent", agent)
    out.setdefault("is_advisory", True)
    out["description"] = desc
    out["note"] = _ADVISORY_NOTE
    return out


@router.get("/api/investment-os")
def index() -> dict:
    """Index of the AI Investment OS analysts + whether each has produced an artifact."""
    analysts = []
    for slug, (rel_path, agent, desc) in _ANALYSTS.items():
        raw = read_state(rel_path, {})
        analysts.append({
            "slug": slug,
            "agent": agent,
            "available": bool(raw and isinstance(raw, dict)),
            "endpoint": f"/api/investment-os/{slug}",
            "description": desc,
        })
    return {"analysts": analysts, "count": len(analysts), "is_advisory": True, "note": _ADVISORY_NOTE}


@router.get("/api/investment-os/stablecoin-yield")
def stablecoin_yield() -> dict:
    return _serve("stablecoin-yield")


@router.get("/api/investment-os/market-regime")
def market_regime() -> dict:
    return _serve("market-regime")


@router.get("/api/investment-os/reporting")
def reporting() -> dict:
    return _serve("reporting")


@router.get("/api/investment-os/red-team")
def red_team() -> dict:
    return _serve("red-team")
