"""Q2-8 — design-partner pilot pipeline tracker (CRM-lite, deterministic, PII-minimal).

The mechanical difference between a plan and a first-AUM funnel: a tracked list of design-partner
prospects with their stage, last-touch, and whether the self-verifying DD artifact (Q2-9 dataroom /
Q2-10 snapshot) was sent. This is the STATE MACHINE + store only — populating it with real prospects is
the owner's action.

**PII-minimal by design (the brand is zero-PII):** a prospect is identified by an OPAQUE owner-chosen
`label` (e.g. "partner-A", a fund's public ticker, a UTM bucket) — NEVER a person's name, email, or any
contact detail. The store holds label + stage + timestamps + non-PII notes. If the owner ever needs
contact details, those live OUTSIDE this repo (a personal CRM), not here. This keeps the funnel machinery
non-custodial + committable-safe.

Deterministic, stdlib-only, LLM-forbidden, fail-CLOSED (an illegal stage transition RAISES; a malformed
store loads as empty rather than crashing). Atomic writes. Advisory — moves no capital, opens no position.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_STORE = _DATA / "pilot" / "prospects.json"

# The fixed stage ladder. Forward-only through the funnel, with terminal DECLINED/STALE reachable from any
# active stage. A transition not in _ALLOWED is refused (fail-closed) so the funnel can't be corrupted.
STAGES = ("LEAD", "DD_SENT", "CONVERSATION", "DILIGENCE", "COMMITTED", "DECLINED", "STALE")
_ACTIVE = ("LEAD", "DD_SENT", "CONVERSATION", "DILIGENCE")
_TERMINAL = ("COMMITTED", "DECLINED", "STALE")
_ALLOWED = {
    "LEAD": {"DD_SENT", "CONVERSATION", "DECLINED", "STALE"},
    "DD_SENT": {"CONVERSATION", "DILIGENCE", "DECLINED", "STALE"},
    "CONVERSATION": {"DILIGENCE", "DECLINED", "STALE"},
    "DILIGENCE": {"COMMITTED", "DECLINED", "STALE"},
    # terminal stages can be re-opened to LEAD (a revived prospect) but nothing else
    "COMMITTED": set(), "DECLINED": {"LEAD"}, "STALE": {"LEAD"},
}

_LABEL_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,64}$")   # opaque label only — no '@', no free-form PII


class PilotError(ValueError):
    """Raised on an illegal transition or a PII-shaped / malformed label (fail-closed)."""


def _load(path: Path) -> list:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save(rows: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(rows, str(path))


def _check_label(label: str) -> str:
    label = (label or "").strip()
    if not _LABEL_RE.match(label):
        raise PilotError(f"label must be an opaque token (letters/digits/space/_.-, <=64), got {label!r} "
                         "— NEVER a name/email/contact (this store is PII-minimal by design)")
    if "@" in label:
        raise PilotError("label looks like an email — PII is not allowed in the pilot store")
    return label


def add_prospect(label: str, *, now_iso: str, note: str = "", store: Optional[Path] = None) -> dict:
    """Add a prospect at stage LEAD. Idempotent on label (returns the existing row if present)."""
    path = store or _STORE
    rows = _load(path)
    label = _check_label(label)
    for r in rows:
        if r.get("label") == label:
            return r
    row = {"label": label, "stage": "LEAD", "created_at": now_iso, "last_touch": now_iso,
           "dd_artifact_sent": False, "note": str(note)[:280]}
    rows.append(row)
    _save(rows, path)
    return row


def advance_stage(label: str, to_stage: str, *, now_iso: str, note: str = "",
                  store: Optional[Path] = None) -> dict:
    """Move a prospect to `to_stage` iff the transition is allowed. fail-CLOSED on an illegal move."""
    path = store or _STORE
    rows = _load(path)
    to_stage = to_stage.upper()
    if to_stage not in STAGES:
        raise PilotError(f"unknown stage {to_stage!r}")
    for r in rows:
        if r.get("label") == label:
            frm = r.get("stage", "LEAD")
            if to_stage != frm and to_stage not in _ALLOWED.get(frm, set()):
                raise PilotError(f"illegal transition {frm} → {to_stage}")
            r["stage"] = to_stage
            r["last_touch"] = now_iso
            if note:
                r["note"] = str(note)[:280]
            _save(rows, path)
            return r
    raise PilotError(f"no prospect labelled {label!r}")


def mark_dd_sent(label: str, *, now_iso: str, store: Optional[Path] = None) -> dict:
    """Record that the self-verifying DD artifact (dataroom/snapshot) was sent + advance LEAD→DD_SENT."""
    path = store or _STORE
    rows = _load(path)
    for r in rows:
        if r.get("label") == label:
            r["dd_artifact_sent"] = True
            r["last_touch"] = now_iso
            if r.get("stage") == "LEAD":
                r["stage"] = "DD_SENT"
            _save(rows, path)
            return r
    raise PilotError(f"no prospect labelled {label!r}")


def summary(store: Optional[Path] = None) -> dict:
    """Deterministic funnel rollup: counts per stage + active/terminal totals + dd-sent count."""
    rows = _load(store or _STORE)
    by_stage: Dict[str, int] = {s: 0 for s in STAGES}
    for r in rows:
        st = r.get("stage", "LEAD")
        if st in by_stage:
            by_stage[st] += 1
    return {
        "model": "pilot_pipeline",
        "is_advisory": True,
        "pii_minimal": True,
        "n_prospects": len(rows),
        "n_active": sum(by_stage[s] for s in _ACTIVE),
        "n_terminal": sum(by_stage[s] for s in _TERMINAL),
        "n_dd_sent": sum(1 for r in rows if r.get("dd_artifact_sent")),
        "by_stage": by_stage,
        "stages": list(STAGES),
        "note": "PII-minimal design-partner funnel (opaque labels only). Advisory — moves no capital.",
    }


def list_prospects(store: Optional[Path] = None) -> List[dict]:
    """All prospect rows (label + stage + timestamps + dd flag). No PII by construction."""
    return _load(store or _STORE)
