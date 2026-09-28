"""Decision seam PROPOSED → Owner Confirm → ACCEPTED (ADR-495), reusing the ADR system as THE decision
authority. Any session may propose a DRAFT; only an Owner-confirmed accept() promotes it to a numbered ADR.
Closes CANONICAL_DECISION_WRITE=NOT_AVAILABLE without inventing a competing authority."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DECISIONS = REPO / "docs" / "decisions"
DRAFTS = DECISIONS / "drafts"
_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG.sub("-", (text or "").lower()).strip("-")[:48] or "decision"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def propose_decision(*, project_id: str, problem: str, decision: str, rationale: str = "",
                     alternatives: str = "", consequences: str = "", evidence: str = "",
                     related_tasks: str = "", owner: str = "@yurii", now_iso: str = "",
                     source: str = "studio-os") -> dict:
    """Write a decision DRAFT (status PROPOSED). Not an accepted decision. Owner accept() required."""
    DRAFTS.mkdir(parents=True, exist_ok=True)
    slug = _slug(problem or decision)
    draft_id = f"DRAFT-{slug}"
    path = DRAFTS / f"{draft_id}.md"
    n = 2
    while path.exists():
        draft_id = f"DRAFT-{slug}-{n}"; path = DRAFTS / f"{draft_id}.md"; n += 1
    body = (f"# {draft_id}: {problem[:80]}\n\n"
            f"- **Status:** PROPOSED · {now_iso} · owner: {owner} · project: {project_id} · source: {source}\n\n"
            f"## Problem\n{problem}\n\n## Decision\n{decision}\n\n## Rationale\n{rationale}\n\n"
            f"## Alternatives\n{alternatives}\n\n## Consequences\n{consequences}\n\n"
            f"## Evidence\n{evidence}\n\n## Related tasks\n{related_tasks}\n\n"
            f"> PROPOSED — not an accepted decision. Owner confirmation promotes this to a numbered ADR.\n")
    path.write_text(body, encoding="utf-8")
    return {"ok": True, "draft_id": draft_id, "status": "PROPOSED",
            "path": _rel(path), "note": "ACCEPTED requires Owner confirm (accept_decision)"}


def _next_adr_number() -> int:
    nums = []
    for d in (DECISIONS, REPO / "docs" / "adr"):
        if d.exists():
            for p in d.glob("ADR[-_]*.md"):
                m = re.search(r"ADR[-_](\d+)", p.name)
                if m:
                    nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def accept_decision(draft_id: str, *, owner: str = "@yurii", now_iso: str = "",
                    owner_confirmed: bool = False) -> dict:
    """Owner-gated: promote a PROPOSED draft to a numbered ACCEPTED ADR. Refuses without owner_confirmed."""
    if not owner_confirmed:
        return {"ok": False, "error": "REFUSED: owner confirmation required for ACCEPTED state"}
    src = DRAFTS / f"{draft_id}.md"
    if not src.exists():
        return {"ok": False, "error": f"no such draft: {draft_id}"}
    draft = src.read_text(encoding="utf-8")
    num = _next_adr_number()
    slug = draft_id.replace("DRAFT-", "", 1)
    adr_id = f"ADR-{num}"
    out = DECISIONS / f"{adr_id}-{slug}.md"
    # promote: swap the header + status to ACCEPTED, keep the body sections
    body = draft.replace(f"# {draft_id}:", f"# {adr_id}:", 1)
    body = re.sub(r"- \*\*Status:\*\* PROPOSED", f"- **Status:** ACCEPTED", body, count=1)
    body = body.replace(f"· owner: {owner}", f"· owner: {owner}", 1)
    body += f"\n> Promoted from {draft_id} on {now_iso} by Owner confirmation (ADR-495 decision seam).\n"
    out.write_text(body, encoding="utf-8")
    src.unlink()   # draft consumed
    return {"ok": True, "adr_id": adr_id, "status": "ACCEPTED",
            "path": _rel(out), "from_draft": draft_id}


STATUSES = ("PROPOSED", "OWNER_REVIEW", "ACCEPTED", "SUPERSEDED", "REJECTED")


def mark_owner_review(draft_id: str) -> dict:
    """Move a PROPOSED draft into OWNER_REVIEW (queued for the Owner). Not ACCEPTED."""
    src = DRAFTS / f"{draft_id}.md"
    if not src.exists():
        return {"ok": False, "error": f"no such draft: {draft_id}"}
    body = re.sub(r"- \*\*Status:\*\* PROPOSED", "- **Status:** OWNER_REVIEW", src.read_text(encoding="utf-8"), count=1)
    src.write_text(body, encoding="utf-8")
    return {"ok": True, "draft_id": draft_id, "status": "OWNER_REVIEW"}


def reject_decision(draft_id: str, *, reason: str = "", owner_confirmed: bool = False, now_iso: str = "") -> dict:
    """Owner-gated: reject a draft (records REJECTED, keeps the record for provenance)."""
    if not owner_confirmed:
        return {"ok": False, "error": "REFUSED: owner confirmation required to reject"}
    src = DRAFTS / f"{draft_id}.md"
    if not src.exists():
        return {"ok": False, "error": f"no such draft: {draft_id}"}
    body = re.sub(r"- \*\*Status:\*\* (PROPOSED|OWNER_REVIEW)", "- **Status:** REJECTED", src.read_text(encoding="utf-8"), count=1)
    body += f"\n> REJECTED on {now_iso} by Owner. Reason: {reason}\n"
    rej = DRAFTS / f"{draft_id}.REJECTED.md"
    rej.write_text(body, encoding="utf-8"); src.unlink()
    return {"ok": True, "draft_id": draft_id, "status": "REJECTED", "path": _rel(rej)}


def supersede_adr(old_adr_id: str, new_adr_id: str, *, now_iso: str = "") -> dict:
    """Mark an ACCEPTED ADR as SUPERSEDED by a newer one (edits its status line, adds superseded_by)."""
    matches = list(DECISIONS.glob(f"{old_adr_id}-*.md")) + list((REPO / "docs" / "adr").glob(f"{old_adr_id}*.md"))
    if not matches:
        return {"ok": False, "error": f"no such ADR: {old_adr_id}"}
    p = matches[0]
    body = re.sub(r"- \*\*Status:\*\* ACCEPTED", f"- **Status:** SUPERSEDED by {new_adr_id}", p.read_text(encoding="utf-8"), count=1)
    body += f"\n> SUPERSEDED by {new_adr_id} on {now_iso}.\n"
    p.write_text(body, encoding="utf-8")
    return {"ok": True, "adr_id": old_adr_id, "status": "SUPERSEDED", "superseded_by": new_adr_id}


def list_drafts() -> list[dict]:
    if not DRAFTS.exists():
        return []
    out = []
    for p in sorted(DRAFTS.glob("*.md")):
        st = "REJECTED" if p.name.endswith(".REJECTED.md") else "PROPOSED"
        txt = p.read_text(encoding="utf-8")
        m = re.search(r"- \*\*Status:\*\* (\w+)", txt)
        out.append({"draft_id": p.stem, "status": (m.group(1) if m else st)})
    return out
