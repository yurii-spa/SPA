"""
spa_core/academy/api/routes/auth.py

Authentication routes for the Academy sub-application.

  POST /auth/register          — invite-gated signup → session cookie + csrf
  POST /auth/login             — password login (unified 401, no enumeration)
  POST /auth/logout            — [auth + csrf] revoke this session
  POST /auth/logout-everywhere — [auth + csrf] revoke all of the user's sessions
  GET  /auth/me                — [auth] current user + progress summary

Session handling:
  - create_session() returns the raw opaque token (cookie value); only its
    sha256 hash is ever stored. We immediately read the session back to obtain
    the per-session CSRF token echoed to the client (double-submit pattern).
  - The cookie is HttpOnly + SameSite=Lax, Secure in prod (SPA_ACADEMY_DEV=1
    relaxes Secure for http://localhost). Path is "/" so the cookie round-trips
    whether the sub-app is reached at "/academy/..." in prod or mounted at root
    under TestClient; the API host serves nothing but the academy here.

Audit note: users.create_user() and users.authenticate() already write the
"register"/"login"/"login_failed" events, so those routes do NOT double-log;
logout/logout-everywhere are logged here (the revoke helpers do not log).

LLM FORBIDDEN in this module (auth/security-adjacent).
Academy stage 3.
"""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events, sessions, users
from spa_core.academy.api.deps import (
    SESSION_COOKIE,
    get_current_user,
    get_db,
    require_csrf,
)

router = APIRouter(prefix="/auth", tags=["academy-auth"])

_SESSION_MAX_AGE = 604800  # 7 days, matches the DB session TTL
_LESSON_IDS = tuple(range(0, 9))  # lessons 0..8


class RegisterBody(BaseModel):
    email: str
    password: str
    invite_code: str


class LoginBody(BaseModel):
    email: str
    password: str


def _is_dev() -> bool:
    return (
        os.environ.get("SPA_ACADEMY_DEV", "").strip() == "1"
        or os.environ.get("ACADEMY_DEV", "").strip() == "1"
    )


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=not _is_dev(),
        samesite="lax",
        path="/",
        max_age=_SESSION_MAX_AGE,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "is_owner": row["is_owner"],
        "created_at": row["created_at"],
    }


def _issue_session(db: AcademyDB, request: Request, user_id: int) -> str:
    """Create a session and return its per-session CSRF token."""
    raw_token = sessions.create_session(
        db,
        user_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    session = sessions.get_session(db, raw_token)
    if session is None:  # pragma: no cover - just created, must exist
        raise HTTPException(status_code=500, detail="session creation failed")
    return raw_token, session["csrf_token"]


@router.post("/register")
def register(
    body: RegisterBody,
    request: Request,
    response: Response,
    db: AcademyDB = Depends(get_db),
) -> dict:
    try:
        user_id = users.create_user(
            db, body.email, body.password, invite_code=body.invite_code
        )
    except ValueError as exc:
        # Invalid email/password or an invalid/exhausted invite.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        # Duplicate email — do not leak which constraint tripped.
        raise HTTPException(status_code=409, detail="email already registered") from exc

    raw_token, csrf_token = _issue_session(db, request, user_id)
    _set_session_cookie(response, raw_token)
    # NOTE: users.create_user() already logged the "register" audit event.
    user = users.get_user_by_id(db, user_id)
    return {"ok": True, "csrf_token": csrf_token, "user": _public_user(user)}


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: AcademyDB = Depends(get_db),
) -> dict:
    # authenticate() is constant-time w.r.t. account existence and logs the
    # "login" / "login_failed" audit event itself.
    user = users.authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")

    raw_token, csrf_token = _issue_session(db, request, user["id"])
    _set_session_cookie(response, raw_token)
    return {"ok": True, "csrf_token": csrf_token, "user": _public_user(user)}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    raw = request.cookies.get(SESSION_COOKIE)
    session = sessions.get_session(db, raw) if raw else None
    if session is not None:
        sessions.revoke_session(db, session["session_id"])
    _clear_session_cookie(response)
    events.log_event(db, "logout", user_id=current_user["id"], ip=_client_ip(request))
    return {"ok": True}


@router.post("/logout-everywhere")
def logout_everywhere(
    request: Request,
    response: Response,
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    sessions.revoke_all_sessions(db, current_user["id"])
    _clear_session_cookie(response)
    events.log_event(
        db, "logout_everywhere", user_id=current_user["id"], ip=_client_ip(request)
    )
    return {"ok": True}


@router.get("/me")
def me(
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT lesson_id, status FROM progress WHERE user_id = ?",
            (current_user["id"],),
        ).fetchall()
    progress = {lesson_id: "not_started" for lesson_id in _LESSON_IDS}
    for row in rows:
        progress[row["lesson_id"]] = row["status"]
    return {
        "email": current_user["email"],
        "is_owner": current_user["is_owner"],
        "created_at": current_user["created_at"],
        "wallets": [],
        "progress_summary": progress,
    }
