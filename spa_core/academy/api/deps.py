"""
spa_core/academy/api/deps.py

FastAPI dependencies for the Academy sub-application.

These wire the stdlib auth core (spa_core.academy.auth.*) into FastAPI's
dependency-injection: resolving the per-request AcademyDB, extracting the
current user from the opaque ``academy_session`` cookie, and enforcing the
double-submit CSRF token + owner-only guards.

Design notes:
  - The DB path is resolved per request via :func:`academy_db_path`, preferring
    ``request.state.db_path`` (set by the app's state middleware) → the mounted
    sub-app's ``app.state.db_path`` → the ``SPA_ACADEMY_DB`` env var. This lets
    tests inject a tmp-file DB while production reads the env.
  - ``get_current_user`` returns the full user Row (incl. password_hash); route
    handlers surface only the public columns.
  - CSRF uses the per-session token stored alongside the session (double-submit):
    a mutating request must echo it in ``X-CSRF-Token``.

LLM FORBIDDEN in this module (auth/security-adjacent).
Academy stage 3.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

from fastapi import Depends, HTTPException, Request

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import sessions, users

# Name of the opaque session cookie handed to the browser.
SESSION_COOKIE = "academy_session"
# Double-submit CSRF header the browser must echo on mutating requests.
CSRF_HEADER = "X-CSRF-Token"


def academy_db_path(request: Request) -> str:
    """Resolve the academy DB path for this request.

    Order: per-request state → mounted sub-app state → SPA_ACADEMY_DB env.
    Raises 500 if none is configured (never guesses a path).
    """
    dbp = getattr(request.state, "db_path", None)
    if not dbp:
        dbp = getattr(request.app.state, "db_path", None)
    if not dbp:
        dbp = os.environ.get("SPA_ACADEMY_DB")
    if not dbp:
        raise HTTPException(status_code=500, detail="academy db not configured")
    return dbp


def get_db(request: Request) -> AcademyDB:
    """FastAPI dependency: an AcademyDB bound to this request's db_path.

    AcademyDB is a lightweight connection factory (each ``.connect()`` opens a
    fresh sqlite3 connection), so returning a new instance per request is cheap
    and thread-safe.
    """
    return AcademyDB(db_path=academy_db_path(request))


def _raw_session_token(request: Request) -> Optional[str]:
    """Extract the raw session token from the request cookie, or None."""
    return request.cookies.get(SESSION_COOKIE)


def get_current_user(
    request: Request,
    db: AcademyDB = Depends(get_db),
) -> sqlite3.Row:
    """Return the authenticated user Row, or raise 401.

    Resolves the opaque cookie → live session → user. A missing/expired/revoked
    session or a dangling user id both surface as a single 401 (no enumeration).
    """
    raw = _raw_session_token(request)
    if not raw:
        raise HTTPException(status_code=401, detail="not authenticated")
    session = sessions.get_session(db, raw)
    if session is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = users.get_user_by_id(db, session["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def require_csrf(
    request: Request,
    db: AcademyDB = Depends(get_db),
) -> None:
    """Enforce the double-submit CSRF token on a mutating request.

    The ``X-CSRF-Token`` header must equal the token bound to the live session
    identified by the ``academy_session`` cookie. Any mismatch — or a missing
    session/header — is a 403.
    """
    raw = _raw_session_token(request)
    if not raw:
        raise HTTPException(status_code=403, detail="csrf: no session")
    session = sessions.get_session(db, raw)
    if session is None:
        raise HTTPException(status_code=403, detail="csrf: no session")
    header = request.headers.get(CSRF_HEADER)
    # secrets.compare_digest keeps the check constant-time; both must be str.
    import secrets as _secrets

    stored = session["csrf_token"]
    if not header or not _secrets.compare_digest(str(header), str(stored)):
        raise HTTPException(status_code=403, detail="csrf: token mismatch")


def require_owner(current_user: sqlite3.Row = Depends(get_current_user)) -> sqlite3.Row:
    """Guard: the current user must be an owner (is_owner == 1), else 403."""
    if current_user["is_owner"] != 1:
        raise HTTPException(status_code=403, detail="owner only")
    return current_user
