"""spa_core/defi_engine/loss_budget.py — each package's loss budget vs what is measured and enforced (P1-7).

The site publishes a drawdown budget per package (``landing/src/lib/tier_bands.json``: Conservative
≤3 %, Balanced ≤10 %, Aggressive ≤25 %). The audit (§C #5) found it display-only: nothing on the money
path reads it, and for Conservative the published 3 % is TIGHTER than the first enforced stop
(SOFT_DERISK at 5 %) — a reader is promised a limit the system does not hold.

This module answers three questions per book, each separately:

1. **consumed** — the WORST drawdown from the running peak over the honest series (the current one
   is reported next to it) as a share of the budget — a budget once spent stays spent: ``ok`` < 50 % · ``watch`` < 80 % · ``warn`` < 100 % · ``breach`` ≥ 100 %;
   no honest series ⇒ ``unmeasured`` (Balanced / Aggressive until their first corrected-model rows);
2. **bound** — is the budget held by an ENFORCED stop at or inside it? Balanced (−8 % ≤ 10 %) and
   Aggressive (−25 % ≤ 25 %) are bound; Conservative (first stop −5 % > 3 %) is NOT;
3. **gap** — for an unbound budget, how far the nearest enforced stop sits outside it.

Binding the Conservative budget (a halt-increase at 3 %) or changing the published 3 % are both
changes the owner owns (a governance rule on the evidenced book / a public number) — ADR-532 names
the gap; it does not close it.

The budgets below are the ONE runtime copy of the published numbers: the production tree does not
carry ``landing/`` (ADR-152), so runtime cannot read the page's file. ``test_defi_engine.py::test_runtime_budget_mirror_equals_the_published_page``
holds this table equal to ``tier_bands.json`` — the page and the engine cannot drift apart silently.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

#: Advisory drawdown budget per package, percent (mirror of tier_bands.json `loss_budget_pct`, parity-tested).
#: Since 2026-10-03 (owner, item 6a) it is no longer printed inside the research-target band.
PUBLISHED_BUDGET_PCT = {"conservative": 3.0, "balanced": 10.0, "aggressive": 25.0}

_LEVELS = ((0.5, "ok"), (0.8, "watch"), (1.0, "warn"))


def drawdown_profile(series: list[dict]) -> dict:
    """Current and worst drawdown from the running peak, in percent (positive = loss)."""
    eqs = [float(r["equity"]) for r in series if isinstance(r.get("equity"), (int, float)) and r["equity"] > 0]
    if len(eqs) < 2:
        return {"measured": False, "reason": f"{len(eqs)} honest equity bar(s) — a drawdown needs ≥ 2"}
    peak, worst = 0.0, 0.0
    for e in eqs:
        peak = max(peak, e)
        worst = max(worst, (1.0 - e / peak) * 100.0)
    current = (1.0 - eqs[-1] / peak) * 100.0
    return {"measured": True, "current_drawdown_pct": round(current, 6),
            "worst_drawdown_pct": round(worst, 6), "bars": len(eqs)}


def _level(frac: float) -> str:
    for edge, name in _LEVELS:
        if frac < edge:
            return name
    return "breach"


def book_budget(book_id: str, book: dict) -> dict:
    budget = PUBLISHED_BUDGET_PCT.get(book_id)
    stops = ((book.get("gate") or {}).get("stops") or [])
    stop_pcts = sorted(float(s["drawdown_pct"]) for s in stops if isinstance(s.get("drawdown_pct"), (int, float)))
    nearest: Optional[float] = stop_pcts[0] if stop_pcts else None
    # None = we do not know the enforced stop (or the budget): NOT "unbound" (invariant #17).
    bound = (None if nearest is None or budget is None else nearest <= budget + 1e-9)
    out = {
        "budget_pct": budget,
        "budget_source": "tier_bands.json loss_budget_pct (advisory, not printed as a band), runtime mirror parity-tested",
        "nearest_enforced_stop_pct": nearest,
        "bound_by_enforced_stop": bound,
        "unbound_gap_pct": (round(nearest - budget, 4) if bound is False else None),
        "bound_reason": None if bound is not None else "enforced stop or budget not readable",
        "enforced": False,
        "note": "advisory: the budget is measured; enforcement is the book's existing stop",
    }
    if not book.get("measured"):
        return {**out, "status": "unmeasured", "reason": book.get("reason")}
    prof = drawdown_profile(book.get("series") or [])
    if not prof.get("measured") or budget is None:
        return {**out, "status": "unmeasured",
                "reason": prof.get("reason") or book.get("series_reason") or "no budget"}
    consumed = prof["worst_drawdown_pct"] / budget
    return {**out, **{k: v for k, v in prof.items() if k != "measured"},
            "consumed_share_of_budget": round(consumed, 6), "status": _level(consumed),
            "series_basis": book.get("series_basis")}
