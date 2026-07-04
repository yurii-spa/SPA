"""
spa_core/academy/api/routes/notes.py

Per-user, per-lesson free-text notes for the Academy sub-application.

  GET /notes/{lesson_id}   — [auth]        return {text, updated_at}
  PUT /notes/{lesson_id}   — [auth + csrf] upsert note text (<=20000 chars)

The SeedPhraseGuard middleware already rejects any body that looks like a raw
private key or a BIP39 seed phrase before it reaches this handler, so a note can
never persist a secret. This router only enforces the size cap and upserts.

LLM FORBIDDEN in this module.
Academy stage 4.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events
from spa_core.academy.api.deps import get_current_user, get_db, require_csrf

router = APIRouter(prefix="/notes", tags=["academy-notes"])

MAX_NOTE_CHARS = 20000


class NoteBody(BaseModel):
    # Pydantic enforces the length cap → a >20000-char body is a 422.
    text: str = Field(..., max_length=MAX_NOTE_CHARS)


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


@router.get("/{lesson_id}")
def get_note(
    lesson_id: int = Path(..., ge=0, le=8),
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """Return this user's note for *lesson_id* (empty string if none)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT text, updated_at FROM notes WHERE user_id = ? AND lesson_id = ?",
            (current_user["id"], lesson_id),
        ).fetchone()
    if row is None:
        return {"lesson_id": lesson_id, "text": "", "updated_at": None}
    return {
        "lesson_id": lesson_id,
        "text": row["text"],
        "updated_at": row["updated_at"],
    }


@router.put("/{lesson_id}")
def put_note(
    body: NoteBody,
    request: Request,
    lesson_id: int = Path(..., ge=0, le=8),
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Upsert this user's note for *lesson_id*. Seed-phrase guard is upstream."""
    uid = current_user["id"]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO notes(user_id, lesson_id, text, updated_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(user_id, lesson_id) DO UPDATE SET "
            "text = excluded.text, updated_at = datetime('now')",
            (uid, lesson_id, body.text),
        )
        row = conn.execute(
            "SELECT text, updated_at FROM notes WHERE user_id = ? AND lesson_id = ?",
            (uid, lesson_id),
        ).fetchone()

    events.log_event(
        db, "note_save", user_id=uid, payload={"lesson_id": lesson_id}, ip=_client_ip(request)
    )
    return {
        "ok": True,
        "lesson_id": lesson_id,
        "text": row["text"],
        "updated_at": row["updated_at"],
    }
