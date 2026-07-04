"""
spa_core/academy/api/routes/admin.py

Owner-only administration surface for the Academy sub-application.

  GET /admin/users               — [owner] every user, WITHOUT password_hash
  GET /admin/progress            — [owner] every progress row, + user email
  GET /admin/events?since=&limit= — [owner] recent audit events (limit ≤ 1000)

All three are guarded by :func:`require_owner` (403 for a non-owner, 401 for an
unauthenticated caller). ``password_hash`` is never selected — the users listing
reuses :func:`spa_core.academy.auth.users.list_users`, which only returns the
public columns. Each successful read writes an ``admin_view`` audit event so the
owner's own inspections are themselves on the append-only record.

Multi-user ready: these endpoints already return the full cross-user picture, so
onboarding a second learner needs no new code here — only a new invite code.

LLM FORBIDDEN in this module (admin/security-adjacent).
Academy stage 9.
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Query, Request

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events, users
from spa_core.academy.api.deps import get_db, require_owner

router = APIRouter(prefix="/admin", tags=["academy-admin"])

# Hard ceiling on how many events a single call may return.
_MAX_EVENTS = 1000
_DEFAULT_EVENTS = 100


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


def _audit(db: AcademyDB, uid: int, view: str, request: Request) -> None:
    """Record that the owner viewed an admin surface (never fail the read)."""
    try:
        events.log_event(
            db, "admin_view", user_id=uid, payload={"view": view}, ip=_client_ip(request)
        )
    except Exception:  # noqa: BLE001
        pass


@router.get("/users")
def admin_users(
    request: Request,
    db: AcademyDB = Depends(get_db),
    owner: sqlite3.Row = Depends(require_owner),
) -> dict:
    """Return every user (public columns only — no password_hash)."""
    rows = users.list_users(db)
    items = [
        {
            "id": r["id"],
            "email": r["email"],
            "invite_code_used": r["invite_code_used"],
            "is_owner": r["is_owner"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    _audit(db, owner["id"], "users", request)
    return {"users": items}


@router.get("/progress")
def admin_progress(
    request: Request,
    db: AcademyDB = Depends(get_db),
    owner: sqlite3.Row = Depends(require_owner),
) -> dict:
    """Return every progress row across all users, joined to the user's email."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT p.user_id AS user_id, u.email AS email, p.lesson_id AS lesson_id, "
            "p.status AS status, p.started_at AS started_at, p.completed_at AS completed_at "
            "FROM progress p JOIN users u ON u.id = p.user_id "
            "ORDER BY p.user_id, p.lesson_id"
        ).fetchall()
    items = [
        {
            "user_id": r["user_id"],
            "email": r["email"],
            "lesson_id": r["lesson_id"],
            "status": r["status"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
        }
        for r in rows
    ]
    _audit(db, owner["id"], "progress", request)
    return {"progress": items}


@router.get("/events")
def admin_events(
    request: Request,
    since: str | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_EVENTS, ge=1, le=_MAX_EVENTS),
    db: AcademyDB = Depends(get_db),
    owner: sqlite3.Row = Depends(require_owner),
) -> dict:
    """Return the most recent audit events (optionally since an ISO8601 cutoff).

    ``limit`` is clamped to [1, 1000] by the query validator; ``since`` filters to
    events with ``created_at > since`` (string compare works because SQLite stores
    ``YYYY-MM-DD HH:MM:SS`` UTC, lexicographically ordered). Newest first.
    """
    params: list = []
    where = ""
    if since:
        where = "WHERE created_at > ?"
        params.append(since)
    params.append(limit)

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, action, payload_json, ip, created_at FROM events "
            f"{where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    items = [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "action": r["action"],
            "payload": json.loads(r["payload_json"]) if r["payload_json"] else None,
            "ip": r["ip"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    _audit(db, owner["id"], "events", request)
    return {"events": items, "count": len(items), "limit": limit, "since": since}
