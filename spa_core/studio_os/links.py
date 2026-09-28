"""Relationship Registry (ADR-497) — LINKS only, never task lifecycle/state. Concurrency-safe:
ONE record per task under data/task_links/<id>.json (parallel branches add different files → no merge
hotspot). Every relation is provenance-typed: EXPLICIT · DERIVED · HEURISTIC · UNKNOWN. Only EXPLICIT and
verified DERIVED relations may feed canonical WHY. Canonical persistence NEVER fails silently — a write
failure returns LINKAGE_WRITE_FAILED (recoverable), task creation still succeeds.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LINKS_DIR = REPO / "data" / "task_links"
LEGACY_JSON = REPO / "data" / "studio_task_links.json"   # read-only migration source

FIELDS = ("project_id", "acceptance_criteria", "decision_refs", "research_refs", "evidence_refs",
          "implementation_commit", "outcome", "handoff_ref", "release_ref", "source", "created_at")
ORIGINS = ("EXPLICIT", "DERIVED", "HEURISTIC", "UNKNOWN")
_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def _path(task_id: str) -> Path:
    return LINKS_DIR / (_SLUG.sub("_", task_id)[:120] + ".json")


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def record_link(task_id: str, *, origin: str = "EXPLICIT", provenance: str = "", **refs) -> dict:
    """Merge canonical references onto ONE per-task record. origin ∈ ORIGINS marks how the refs were
    obtained. Returns {ok:False, error:'LINKAGE_WRITE_FAILED'} on write failure — never a silent pass."""
    if origin not in ORIGINS:
        origin = "UNKNOWN"
    try:
        LINKS_DIR.mkdir(parents=True, exist_ok=True)
        p = _path(task_id)
        rec = {}
        if p.exists():
            rec = json.loads(p.read_text(encoding="utf-8"))
        rec.setdefault("task_id", task_id)
        rec.setdefault("refs", {})
        rec.setdefault("origins", {})
        for k, v in refs.items():
            if k in FIELDS and v not in (None, "", [], {}):
                rec["refs"][k] = v
                rec["origins"][k] = origin          # per-field origin (explicit vs derived vs heuristic)
        if provenance:
            rec["provenance"] = provenance
        try:
            from spa_core.utils.atomic import atomic_save
            atomic_save(rec, str(p))
        except Exception:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(p)
        return {"ok": True, "task_id": task_id, "path": _rel(p), "record": rec}
    except Exception as exc:  # surfaced, NOT swallowed (ADR-497)
        return {"ok": False, "error": "LINKAGE_WRITE_FAILED", "task_id": task_id, "detail": str(exc)}


def get_link(task_id: str) -> dict | None:
    """Return a flat link view {field: value, _origins: {...}} for a task id (exact, then fuzzy contains)."""
    def _flat(rec):
        out = dict(rec.get("refs", {}))
        out["_origins"] = rec.get("origins", {})
        if rec.get("provenance"):
            out["provenance"] = rec["provenance"]
        return out
    p = _path(task_id)
    if p.exists():
        try:
            return _flat(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
    # fuzzy: a work-item id that contains the card stem (or vice-versa)
    for rec in _iter_records():
        tid = rec.get("task_id", "")
        if tid and (tid in task_id or task_id in tid):
            return _flat(rec)
    return None


def _iter_records():
    if LINKS_DIR.exists():
        for f in sorted(LINKS_DIR.glob("*.json")):
            try:
                yield json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    # legacy single-file (read-only, for a one-time migration/backread)
    if LEGACY_JSON.exists():
        try:
            for tid, refs in (json.loads(LEGACY_JSON.read_text(encoding="utf-8")).get("links") or {}).items():
                if tid not in {r.get("task_id") for r in _dir_ids()}:
                    yield {"task_id": tid, "refs": {k: v for k, v in refs.items() if k in FIELDS},
                           "origins": {k: "HEURISTIC" for k in refs if k in FIELDS},
                           "provenance": refs.get("provenance", "legacy studio_task_links.json")}
        except (OSError, ValueError):
            pass


def _dir_ids():
    if LINKS_DIR.exists():
        for f in LINKS_DIR.glob("*.json"):
            try:
                yield json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue


def all_links() -> dict:
    """{task_id: {field: value, _origins: {...}}} across per-task records (+ legacy backread)."""
    out = {}
    for rec in _iter_records():
        tid = rec.get("task_id")
        if not tid:
            continue
        flat = dict(rec.get("refs", {}))
        flat["_origins"] = rec.get("origins", {})
        if rec.get("provenance"):
            flat["provenance"] = rec["provenance"]
        out.setdefault(tid, flat)
    return out
