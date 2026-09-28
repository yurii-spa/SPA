"""Session handoff records (ADR-497) — ONE session = ONE immutable file under data/handoffs/, so parallel
AI branches never collide on a single append-only file. Outcomes/evidence only, never chain-of-thought.
The journal (docs/journal/) stays the prose authority; these are the machine-readable index. Legacy
data/studio_handoffs.jsonl is still read for backward continuity."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HANDOFF_DIR = REPO / "data" / "handoffs"
LEGACY_LEDGER = REPO / "data" / "studio_handoffs.jsonl"   # read-only backread

FIELDS = ("requested", "done", "changed", "decisions", "evidence", "tests",
          "commits", "open_questions", "blockers", "next_action", "owner_action")
_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def _rel(p):
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def write_handoff(project_id: str, *, now_iso: str, **fields) -> dict:
    """Write one immutable per-session record. Returns {ok, path} or {ok:False, error} — never silent."""
    rec = {"project_id": project_id, "ts": now_iso}
    for f in FIELDS:
        rec[f] = fields.get(f)
    try:
        HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
        name = _SLUG.sub("_", f"{now_iso}-{project_id}")[:120] + ".json"
        p = HANDOFF_DIR / name
        n = 2
        while p.exists():
            p = HANDOFF_DIR / (name[:-5] + f"-{n}.json"); n += 1
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"ok": True, "path": _rel(p), "record": rec}
    except Exception as exc:  # surfaced, not swallowed
        return {"ok": False, "error": "HANDOFF_WRITE_FAILED", "detail": str(exc), "record": rec}


def _all_records():
    recs = []
    if HANDOFF_DIR.exists():
        for f in sorted(HANDOFF_DIR.glob("*.json")):
            try:
                recs.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    if LEGACY_LEDGER.exists():   # backread the old append-only ledger
        for ln in LEGACY_LEDGER.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    recs.append(json.loads(ln))
                except ValueError:
                    continue
    return recs


def last_handoff(project_id: str | None = None) -> dict | None:
    recs = _all_records()
    recs.sort(key=lambda r: str(r.get("ts", "")))
    for r in reversed(recs):
        if project_id is None or r.get("project_id") == project_id:
            return r
    return None


def build_index() -> dict:
    """Disposable generated index over all handoff records (per-session files + legacy)."""
    recs = _all_records()
    recs.sort(key=lambda r: str(r.get("ts", "")))
    return {"schema": "studio-os/handoff-index/1", "count": len(recs),
            "sessions": [{"ts": r.get("ts"), "project_id": r.get("project_id"),
                          "done": (r.get("done") or "")[:120], "next_action": r.get("next_action")}
                         for r in recs]}
