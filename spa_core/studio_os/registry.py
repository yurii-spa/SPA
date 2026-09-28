"""Project Registry reader/validator (ADR-495). Projects are first-class objects with POINTERS to canon."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "data" / "studio_projects.json"

REQUIRED = ("project_id", "name", "purpose", "status", "owner", "repositories",
            "canonical_docs", "task_sources", "decision_sources", "updated_at")


def load_registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"projects": [], "present": False}


def project_ids() -> list[str]:
    return [p.get("project_id") for p in load_registry().get("projects", [])]


def get_project(project_id: str) -> dict | None:
    for p in load_registry().get("projects", []):
        if p.get("project_id") == project_id:
            return p
    return None


def validate() -> list[str]:
    """Return a list of problems; empty = valid. Every project must carry the required pointer fields."""
    problems = []
    reg = load_registry()
    seen = set()
    for p in reg.get("projects", []):
        pid = p.get("project_id")
        if not pid:
            problems.append("project without project_id"); continue
        if pid in seen:
            problems.append(f"duplicate project_id {pid}")
        seen.add(pid)
        for f in REQUIRED:
            if not p.get(f):
                problems.append(f"{pid}: missing '{f}'")
    return problems
