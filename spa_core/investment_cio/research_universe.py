"""Investment CIO — the research_universe READ-TIME projection (ADR-560 WP-S07 / binding #14).

NON-SLEEVE. This is deliberately NOT part of :data:`spa_core.investment_cio.contract.SLEEVES`,
never an input to :mod:`spa_core.investment_cio.policy`, and never written into a ledger record
(``contract.REC_FIELDS`` is frozen). It is built fresh, at READ time, by
:func:`spa_core.investment_cio.read.latest` from
``spa_core.research_factory.read.cio_view(data_dir, now)`` and exposed as its own top-level key —
Oracle (the CIO) can SEE the research universe without being able to ALLOCATE it: a future
research sleeve row would need its own ADR (ADR-560 §WP-S07) before any weight can depend on it.

Broken / stale / missing research data degrades only this view (an explicit state, never a
silently empty list) — the CIO's recommendation, weights and ledger record are completely
unaffected either way (see the differential test in
``spa_core/tests/test_investment_cio_research_universe.py``).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STATE_OK = "OK"
STATE_STALE = "STALE"
STATE_BROKEN = "BROKEN"
STATE_NOT_MEASURED = "NOT_MEASURED"
VIEW_STATES = (STATE_OK, STATE_STALE, STATE_BROKEN, STATE_NOT_MEASURED)

# ── Oracle's own three-bucket vocabulary (ADR-564 decision #9) ─────────────────────────────────
#: the factory's ``observe_only`` bucket is what Oracle may only RESEARCH (never allocate, never
#: even consider); ``paper_active`` already folds in EVIDENCE_ACCUMULATING upstream
#: (research_factory.read.cio_view — a paper-active-plus-counted-evidence candidate is still only
#: "evaluated forward with simulated capital", never allocatable on its own); ``cio_eligible`` is
#: the only bucket :func:`research_sleeve_allocatable` will ever say yes to, and even that needs a
#: future sleeve row's own ADR (none exists today).
RESEARCH_ONLY = "RESEARCH_ONLY"
PAPER_ACTIVE = "PAPER_ACTIVE"
CIO_ELIGIBLE = "CIO_ELIGIBLE"
VISIBILITY_BUCKETS = (RESEARCH_ONLY, PAPER_ACTIVE, CIO_ELIGIBLE)


def _empty(state: str, reason: str) -> dict:
    return {"state": state, "reason": reason, "observe_only": [], "paper_active": [], "cio_eligible": [],
            "correlation_groups": {}, "ledger_head_hash": None}


def build(data_dir: Path, now: Optional[datetime] = None) -> dict:
    """Project ``research_factory.read.cio_view`` into the CIO's own read model.

    Never raises: an ``ImportError`` (packages A/B of ADR-560 not deployed yet on this tree), an
    unexpected exception from the factory's reader, or an unexpected return shape all become an
    explicit state here (NOT_MEASURED / BROKEN) — never a crash, and never a silently-empty view
    mistaken for "the factory looked and found nothing" (invariant #17).
    """
    now = now or datetime.now(timezone.utc)
    try:
        from spa_core.research_factory import read as rf_read
    except ImportError as exc:
        return _empty(STATE_NOT_MEASURED, f"research_factory not available ({exc})")
    try:
        view = rf_read.cio_view(Path(data_dir), now)
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: a broken read is never "nothing found"
        return _empty(STATE_BROKEN, f"research_factory.read.cio_view raised {type(exc).__name__}: {exc}")
    if not isinstance(view, dict) or "state" not in view:
        return _empty(STATE_BROKEN, "research_factory.read.cio_view returned an unexpected shape")
    state = view.get("state")
    if state not in VIEW_STATES:
        return _empty(STATE_BROKEN, f"research_factory.read.cio_view returned an unknown state {state!r}")
    return {
        "state": state,
        "reason": view.get("reason"),
        "observe_only": list(view.get("observe_only") or []),
        "paper_active": list(view.get("paper_active") or []),
        "cio_eligible": list(view.get("cio_eligible") or []),
        "correlation_groups": dict(view.get("correlation_groups") or {}),
        "ledger_head_hash": view.get("ledger_head_hash"),
    }


def visibility(view: dict) -> dict:
    """Oracle's own three buckets, exposed SEPARATELY under their own names (ADR-564 decision #9)
    — a read-time relabelling of :func:`build`'s ``observe_only`` / ``paper_active`` /
    ``cio_eligible`` lists, never a second computation of membership. A malformed/absent view
    answers with every bucket ``None`` (not measured), never an empty list that could be misread
    as "nothing in that bucket today"."""
    if not isinstance(view, dict):
        return {RESEARCH_ONLY: None, PAPER_ACTIVE: None, CIO_ELIGIBLE: None}
    return {RESEARCH_ONLY: list(view.get("observe_only") or []),
            PAPER_ACTIVE: list(view.get("paper_active") or []),
            CIO_ELIGIBLE: list(view.get("cio_eligible") or [])}


def _candidate_entries(entries: Any) -> list:
    """[(candidate_id, exposure_key_version_or_None), …]. ``None`` means the view's entry did not
    declare a version (a bare candidate_id, or a dict without the field) — matched by id alone.
    An entry that DOES declare a version is matched strictly: a mismatched version never passes,
    even for the same candidate_id (that is the whole point of binding #14)."""
    out = []
    for e in entries or []:
        if isinstance(e, dict):
            out.append((e.get("candidate_id"), e.get("exposure_key_version")))
        else:
            out.append((e, None))
    return out


def research_sleeve_allocatable(contract_flag: bool, candidate_id: str, exposure_key_version: int,
                                view: dict) -> bool:
    """ADR-560 WP-S07 / binding #14: FOR FUTURE USE ONLY — no research sleeve row exists yet, and
    this is never called from :mod:`spa_core.investment_cio.policy`.

    Membership in ``PAPER_ACTIVE`` alone (ADR-564 decision #9) — whether or not the upstream
    candidate has also reached EVIDENCE_ACCUMULATING, which the factory already folds into the
    same bucket — is NEVER sufficient: only ``CIO_ELIGIBLE`` membership can ever return True here.
    "Evaluated forward with simulated capital" is not "safe to allocate".

    Fail-CLOSED by construction: True only if ALL of —
      1. ``contract_flag`` is literally True (a future sleeve row's own static flag);
      2. ``view["state"] == "OK"`` (not STALE / BROKEN / NOT_MEASURED);
      3. ``candidate_id`` appears in ``view["cio_eligible"]``, and when that entry declares an
         ``exposure_key_version`` it matches the one asked for (a mismatched version is a
         different candidate wearing the old name, never allocatable).
    Any other combination — flag False, a degraded view, or no matching entry — returns False.
    Never True by default.
    """
    if contract_flag is not True:
        return False
    if not isinstance(view, dict) or view.get("state") != STATE_OK:
        return False
    for cid, ver in _candidate_entries(view.get("cio_eligible")):
        if cid == candidate_id and (ver is None or ver == exposure_key_version):
            return True
    return False
