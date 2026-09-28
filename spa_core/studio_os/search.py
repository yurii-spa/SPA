"""Deterministic, local global search over Studio OS objects (ADR-495). No AI, no external service.
Indexes projects / decisions / tasks / research / releases / handoffs from canonical sources and returns
typed references for a substring/keyword query (e.g. "Position Passport")."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(p):
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_index() -> list[dict]:
    """Each item: {type, id, title, ref, text}. Cheap to rebuild; not persisted."""
    idx: list[dict] = []
    # projects
    try:
        reg = json.loads((REPO / "data" / "studio_projects.json").read_text(encoding="utf-8"))
        for p in reg.get("projects", []):
            idx.append({"type": "project", "id": p["project_id"], "title": p["name"],
                        "ref": "data/studio_projects.json", "text": p.get("purpose", "")})
    except (OSError, ValueError, KeyError):
        pass
    # decisions (title from filename + first heading); index the INDEX rows too
    dec = REPO / "docs" / "decisions"
    if dec.exists():
        for f in sorted(dec.glob("ADR-*.md"))[:600]:
            t = _read(f)
            m = re.search(r"^#\s*(.+)$", t, re.M)
            head = m.group(1).strip() if m else f.stem
            parts = f.stem.split("-")
            idx.append({"type": "decision", "id": (parts[0] + "-" + parts[1]) if len(parts) > 1 else f.stem,
                        "title": head, "ref": f"docs/decisions/{f.name}", "text": head + " " + t[:800]})
    # session reports / handoff prose (where recent concepts like "Position Passport" are described)
    rev = REPO / "docs" / "studio_shell_visual_review"
    if rev.exists():
        for f in sorted(rev.glob("*.md")):
            idx.append({"type": "report", "id": f.stem, "title": f.stem.replace("_", " "),
                        "ref": f"docs/studio_shell_visual_review/{f.name}", "text": _read(f)})
    # drafts (proposed decisions)
    dr = dec / "drafts"
    if dr.exists():
        for f in sorted(dr.glob("*.md")):
            idx.append({"type": "decision-draft", "id": f.stem, "title": f.stem,
                        "ref": f"docs/decisions/drafts/{f.name}", "text": _read(f)[:400]})
    # tasks (tracker board rows)
    board = REPO / "nimbalyst-local" / "tracker" / "_BOARD.md"
    if board.exists():
        for ln in _read(board).splitlines():
            if "inbox-" in ln or "own-" in ln or "agent-" in ln:
                idx.append({"type": "task", "id": ln.strip()[:60], "title": ln.strip()[:100],
                            "ref": "nimbalyst-local/tracker/_BOARD.md", "text": ln.strip()})
    # research
    rdir = REPO / "research"
    if rdir.exists():
        for f in sorted(rdir.glob("*.md")):
            idx.append({"type": "research", "id": f.stem, "title": f.stem,
                        "ref": f"research/{f.name}", "text": _read(f)[:400]})
    # releases (golive + changelog)
    for rel in ("PROJECT_CONTROL/11_CHANGELOG.md", "data/golive_status.json"):
        p = REPO / rel
        if p.exists():
            idx.append({"type": "release", "id": rel, "title": rel, "ref": rel, "text": _read(p)[:400]})
    # handoffs
    ho = REPO / "data" / "studio_handoffs.jsonl"
    if ho.exists():
        for ln in _read(ho).splitlines():
            if ln.strip():
                idx.append({"type": "handoff", "id": ln[:40], "title": "handoff",
                            "ref": "data/studio_handoffs.jsonl", "text": ln})
    return idx


def search(query: str, *, limit: int = 20, index=None) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    terms = [t for t in re.split(r"\s+", q) if t]
    idx = index if index is not None else build_index()
    scored = []
    for it in idx:
        hay = (str(it.get("title", "")) + " " + str(it.get("text", ""))).lower()
        score = sum(hay.count(t) for t in terms)
        # require all terms present (AND) for precision
        if all(t in hay for t in terms) and score:
            scored.append((score, it))
    scored.sort(key=lambda s: -s[0])
    return [{"type": it["type"], "id": it["id"], "title": it["title"], "ref": it["ref"], "score": sc}
            for sc, it in scored[:limit]]
