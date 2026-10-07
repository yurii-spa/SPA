"""Truth semantics — what a source's text is ALLOWED to claim.

Statuses (closed set):
    PROPOSED    suggested, not decided            ACCEPTED   decided (an ADR with an accepted status)
    ACTIVE      decided AND currently in force    SUPERSEDED replaced by a later decision/source
    REJECTED    decided against / withdrawn       OBSERVED   a record of what happened (journals, logs)
    UNKNOWN     not enough evidence to say
A chat statement is never any of the decided statuses: chat is not ingested at all. An episodic
record is OBSERVED at most. A previous permission is not a new permission — permissions come only
from the canonical permission sources (CLAUDE.md three owner subjects, ADR-285), never from history.

Status comes from, in order:
  1. architecture/memory_truth.json — explicit, reasoned overrides (e.g. superseded roadmaps);
  2. supersession found in canonical text («Supersedes ADR-N», «заменяет ADR-N», «SUPERSEDES …»);
  3. the source's own status line («Status: ACCEPTED», «Статус: …»);
  4. the source layer (EPISODIC ⇒ OBSERVED); otherwise UNKNOWN.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

STATUSES = ("PROPOSED", "ACCEPTED", "ACTIVE", "SUPERSEDED", "REJECTED", "OBSERVED", "UNKNOWN")

_STATUS_LINE = re.compile(r"(?im)^[\s>*\-]*(?:\*\*)?(?:status|статус)(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*([^\n]{0,120})")
_SUPERSEDES = re.compile(
    r"(?i)(?:supersedes|заменяет|отменяет|SUPERSEDES)\s*[:\s]*((?:(?:ADR|ADR-B)[-\s]?[\w.]+[,\s]*(?:and|и)?\s*)+)")
_ID = re.compile(r"\bADR-(?:B)?[\d][\w.]*", re.I)


def classify_status_text(s: str) -> str:
    t = (s or "").lower()
    if not t.strip():
        return "UNKNOWN"
    if any(w in t for w in ("supersed", "замен", "устарел", "obsolete")):
        return "SUPERSEDED"
    if any(w in t for w in ("reject", "withdrawn", "отклон", "отозван")):
        return "REJECTED"
    if any(w in t for w in ("proposed", "draft", "предлож", "черновик", "under review", "под ревью")):
        return "PROPOSED"
    if any(w in t for w in ("accepted", "принят", "approved", "одобрен", "active", "действу")):
        return "ACCEPTED"
    return "UNKNOWN"


def status_of_text(text: str) -> Optional[str]:
    m = _STATUS_LINE.search(text[:4000])
    return classify_status_text(m.group(1)) if m else None


def superseded_ids(text: str) -> List[str]:
    out = []
    for m in _SUPERSEDES.finditer(text):
        # a sentence-final period is punctuation, not part of the id («Supersedes ADR-554.» — ADR-610)
        out += [x.upper().replace(" ", "-").rstrip(".") for x in _ID.findall(m.group(1))]
    return out


def load_registry(path: Path) -> Dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"overrides": []}


class Truth:
    """Resolve the status of a source. `docs` = [(key, layer, kind, text)] for the canonical pass."""

    def __init__(self, registry: Dict, docs: Iterable[tuple]):
        self.overrides = {o["path"]: o for o in registry.get("overrides", [])}
        self.superseded_by: Dict[str, str] = {}
        for key, layer, kind, text in docs:
            if layer != "CANONICAL" or kind != "adr":
                continue
            me = adr_id(key)
            for sid in superseded_ids(text):
                if sid != me:
                    self.superseded_by.setdefault(sid, me or key)

    def resolve(self, key: str, layer: str, text: str) -> Dict:
        o = self.overrides.get(key)
        if o:
            return {"status": o["status"], "basis": "truth-registry", "superseded_by": o.get("superseded_by"),
                    "reason": o.get("reason")}
        aid = adr_id(key)
        if aid and aid in self.superseded_by:
            return {"status": "SUPERSEDED", "basis": "superseded-in-canon", "superseded_by": self.superseded_by[aid]}
        if key.startswith("shadow:"):
            return {"status": "UNKNOWN", "basis": "off-origin worktree — not canonical"}
        if layer == "EPISODIC":
            return {"status": "OBSERVED", "basis": "layer"}
        st = status_of_text(text)
        if st:
            return {"status": st, "basis": "status-line"}
        return {"status": "UNKNOWN", "basis": "no-evidence"}


def adr_id(key: str) -> Optional[str]:
    m = re.search(r"(ADR-B?[\d][\w.]*?)(?:-[a-z]|\.md|$)", key.split("/")[-1], re.I)
    return m.group(1).upper() if m else None
