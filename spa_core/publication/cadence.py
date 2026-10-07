"""The ONE publication cadence rule (PRODUCT-TRUTH-02, ADR-630; owner rule ADR-357 п. 5: weekly).

Defect it closes (audit 2026-10-07): ``next_publication`` was ``published_at + 7`` of whichever copy a
reader happened to open, and ``published_at`` was stamped when the shelf was BUILT on the Mac — not when
it reached the public. A shelf built on 10-05 that never shipped made the freshness monitor say «next
10-12» while the site (origin copy, published 10-01) and Director said «next 10-08».

Rule: the clock runs from the PUBLISHED shelf — the copy on origin, which Cloudflare Pages builds — and
from nothing else.

**One operand (decided, review 07.10):** on this machine the published copy is the ORIGIN MIRROR
(`~/Documents/SPA_mirror`, synced from origin every 30 min, ADR-152), or an explicit path /
``$SPA_PUBLISHED_SHELF``. Every reader resolves it through :func:`read_published`. No location ⇒ NOT
MEASURED — never the prod tree's own file, which is where an UNSHIPPED build lives. The freshness monitor
keeps its fresh `git show origin/main` for the visitor comparison (ADR-580 C12), but its CADENCE verdict
uses this same operand, so builder, monitor and Director cannot disagree about the date. Every reader (the shelf builder's ``--if-due``, the freshness monitor, Director's
product cells, the continuity generator) asks THIS module, with the published copy, and gets the same
date for the same input.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

CADENCE_DAYS = 7
CADENCE = "weekly"
SHELF_REL = Path("landing") / "src" / "data" / "site_numbers.json"
#: The origin mirror the fleet already keeps (ADR-152) — the published copy on this machine.
DEFAULT_MIRROR = Path.home() / "Documents" / "SPA_mirror"


def published_shelf_path(explicit: "Path | str | None" = None) -> Optional[Path]:
    """Where the PUBLISHED shelf is read: explicit → $SPA_PUBLISHED_SHELF → the origin mirror.
    None ⇒ not measurable here; callers must say so, never fall back to an unshipped local copy."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("SPA_PUBLISHED_SHELF", "").strip()
    if env:
        return Path(env)
    p = DEFAULT_MIRROR / SHELF_REL
    return p if p.is_file() else None


def _read(path: Optional[Path]) -> Optional[dict]:
    if path is None:
        return None
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def published_at(doc: Optional[dict]) -> Optional[str]:
    try:
        return date.fromisoformat(str((doc or {}).get("published_at"))).isoformat()
    except ValueError:
        return None


def next_publication(published: Optional[str]) -> Optional[str]:
    """``published`` ISO date of the PUBLISHED shelf ⇒ the next weekly slot. Unknown ⇒ None."""
    try:
        return (date.fromisoformat(str(published)) + timedelta(days=CADENCE_DAYS)).isoformat()
    except ValueError:
        return None


def status(shelf_doc: Optional[dict], *, today: Optional[str] = None) -> dict:
    """The verdict every reader prints. Three outcomes: due · not due · NOT MEASURED (shelf unreadable)."""
    pub = published_at(shelf_doc)
    now = date.fromisoformat(today) if today else date.today()
    if pub is None:
        return {"measured": False, "published_at": None, "next_publication": None, "due": True,
                "reason": "published shelf not readable — the date of the last publication is NOT MEASURED"}
    nxt = next_publication(pub)
    age = (now - date.fromisoformat(pub)).days
    due = age >= CADENCE_DAYS
    declared = (shelf_doc or {}).get("next_publication")
    out = {"measured": True, "published_at": pub, "next_publication": nxt, "due": due, "age_days": age,
           "reason": (f"since publication {pub}: {age} d" + (" — due" if due else f" of {CADENCE_DAYS}"))}
    if declared is not None and declared != nxt:
        out["declared_conflict"] = f"the shelf itself declares next {declared!r}, the rule gives {nxt!r}"
    return out


def status_of_published(explicit: "Path | str | None" = None, *, today: Optional[str] = None) -> dict:
    path = published_shelf_path(explicit)
    out = status(_read(path), today=today)
    out["source"] = str(path) if path else None
    if path is None:
        out["reason"] = "published shelf location unknown (no mirror, no $SPA_PUBLISHED_SHELF) — NOT MEASURED"
    return out


def read_published(explicit: "Path | str | None" = None) -> tuple[Optional[dict], str]:
    """THE operand every reader uses. ``(doc, "measured")`` or ``(None, "unmeasured:<reason>")``."""
    path = published_shelf_path(explicit)
    if path is None:
        return None, "unmeasured:published_shelf_location_unknown(no mirror, no $SPA_PUBLISHED_SHELF)"
    doc = _read(path)
    if doc is None:
        return None, f"unmeasured:published_shelf_unreadable:{path}"
    return doc, "measured"


def built_not_delivered(local_doc: Optional[dict], published_doc: Optional[dict]) -> bool:
    """A shelf built here is newer than the one the public sees ⇒ it awaits delivery (owner gate)."""
    lp, pp = published_at(local_doc), published_at(published_doc)
    return bool(lp and pp and lp > pp)
