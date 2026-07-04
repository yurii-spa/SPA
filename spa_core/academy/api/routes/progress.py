"""
spa_core/academy/api/routes/progress.py

Per-user lesson progress for the Academy sub-application.

  GET  /progress   — [auth]        list all 9 modules' progress for the caller
  POST /progress   — [auth + csrf] start a lesson (action="start")

Progress is a per-(user, lesson) row in the ``progress`` table with a status of
not_started / in_progress / submitted / verified / failed. This router only ever
transitions ``not_started -> in_progress`` (action="start"); the richer
transitions (submitted/verified/failed) belong to the verify router built in a
later stage. A GET lazily materialises ``not_started`` rows for any lesson the
user has never touched so the client always sees all 9 modules.

LLM FORBIDDEN in this module.
Academy stage 4.
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events
from spa_core.academy.content.modules import LESSON_IDS
from spa_core.academy.api.deps import get_current_user, get_db, require_csrf

router = APIRouter(prefix="/progress", tags=["academy-progress"])


class StartBody(BaseModel):
    lesson_id: int = Field(..., ge=0, le=8)
    action: str


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


def _evidence_summary(evidence_json) -> dict:
    """Return a compact, non-sensitive summary of the evidence blob (or {})."""
    if not evidence_json:
        return {}
    try:
        data = json.loads(evidence_json)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Only surface small scalar hints — never echo raw nested payloads back.
    summary = {}
    for key in ("kind", "tx_hash", "chain", "verified_at", "score"):
        if key in data:
            summary[key] = data[key]
    return summary


@router.get("")
def list_progress(
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """Return progress for all 9 modules, materialising missing rows lazily."""
    uid = current_user["id"]
    with db.connect() as conn:
        rows = {
            row["lesson_id"]: row
            for row in conn.execute(
                "SELECT lesson_id, status, started_at, completed_at, evidence_json "
                "FROM progress WHERE user_id = ?",
                (uid,),
            ).fetchall()
        }
        # Insert not_started rows for any lesson the user has never touched.
        missing = [lid for lid in LESSON_IDS if lid not in rows]
        for lid in missing:
            conn.execute(
                "INSERT OR IGNORE INTO progress(user_id, lesson_id, status) "
                "VALUES (?, ?, 'not_started')",
                (uid, lid),
            )

    items = []
    for lid in LESSON_IDS:
        row = rows.get(lid)
        if row is None:
            items.append(
                {
                    "lesson_id": lid,
                    "status": "not_started",
                    "started_at": None,
                    "completed_at": None,
                    "evidence": {},
                }
            )
        else:
            items.append(
                {
                    "lesson_id": lid,
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "evidence": _evidence_summary(row["evidence_json"]),
                }
            )
    return {"progress": items}


@router.post("")
def start_lesson(
    body: StartBody,
    request: Request,
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Start a lesson: not_started -> in_progress. Only action="start" is valid."""
    if body.action != "start":
        raise HTTPException(status_code=400, detail="unsupported action")

    uid = current_user["id"]
    lid = body.lesson_id
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT status FROM progress WHERE user_id = ? AND lesson_id = ?",
            (uid, lid),
        ).fetchone()
        if existing is not None and existing["status"] != "not_started":
            # Already started (or further along) — starting again is a conflict.
            raise HTTPException(status_code=409, detail="lesson already started")

        conn.execute(
            "INSERT INTO progress(user_id, lesson_id, status, started_at) "
            "VALUES (?, ?, 'in_progress', datetime('now')) "
            "ON CONFLICT(user_id, lesson_id) DO UPDATE SET "
            "status = 'in_progress', started_at = datetime('now')",
            (uid, lid),
        )
        row = conn.execute(
            "SELECT status, started_at FROM progress "
            "WHERE user_id = ? AND lesson_id = ?",
            (uid, lid),
        ).fetchone()

    events.log_event(
        db, "lesson_start", user_id=uid, payload={"lesson_id": lid}, ip=_client_ip(request)
    )
    return {
        "ok": True,
        "lesson_id": lid,
        "status": row["status"],
        "started_at": row["started_at"],
    }
