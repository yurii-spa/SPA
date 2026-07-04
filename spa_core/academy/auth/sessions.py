"""
spa_core/academy/auth/sessions.py

Opaque server-side session tokens for the Academy.

Threat model / design:
  - The raw token handed to the browser (cookie value) is NEVER stored. Only
    sha256(raw_token) is persisted as the primary key, so a DB read-only leak
    does not hand an attacker usable session cookies.
  - Each session carries a per-session CSRF token (double-submit pattern).
  - Sessions expire on a 7-day sliding window; refresh_session extends it.
  - get_session is the single authoritative read: it transparently filters out
    revoked and expired rows in SQL, so callers never see a dead session.

All timestamps use SQLite's datetime('now') (UTC, 'YYYY-MM-DD HH:MM:SS'),
consistently for both writes and comparisons, so lexical string comparison is
also chronological.

LLM FORBIDDEN in this module (auth/security-adjacent).
Academy stage 2.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from typing import Optional


# 7-day session window (kept as a SQLite modifier string).
_SESSION_TTL = "+7 days"


def _hash_token(raw_token: str) -> str:
    """Return the sha256 hex digest used as the DB session_id."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(
    db,
    user_id: int,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Create a session for *user_id* and return the raw token (cookie value).

    The raw token is returned to the caller exactly once; only its sha256 hash
    is stored. A fresh CSRF token is generated and stored alongside.
    """
    raw_token = secrets.token_urlsafe(32)
    session_id = _hash_token(raw_token)
    csrf_token = secrets.token_hex(32)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions "
            "(session_id, user_id, csrf_token, expires_at, ip, user_agent) "
            "VALUES (?, ?, ?, datetime('now', ?), ?, ?)",
            (session_id, user_id, csrf_token, _SESSION_TTL, ip, user_agent),
        )
    return raw_token


def get_session(db, raw_token: str) -> Optional[sqlite3.Row]:
    """Return the live session Row for *raw_token*, or None.

    None is returned when the token is unknown, the session was revoked
    (revoked_at IS NOT NULL), or it has expired (expires_at <= now).
    """
    if not raw_token:
        return None
    session_id = _hash_token(raw_token)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions "
            "WHERE session_id = ? "
            "  AND revoked_at IS NULL "
            "  AND expires_at > datetime('now')",
            (session_id,),
        ).fetchone()
    return row


def revoke_session(db, session_id: str) -> None:
    """Revoke a single session by its stored session_id (sha256 hash)."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = datetime('now') "
            "WHERE session_id = ? AND revoked_at IS NULL",
            (session_id,),
        )


def revoke_all_sessions(db, user_id: int) -> None:
    """Revoke every live session for *user_id* (logout-everywhere)."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = datetime('now') "
            "WHERE user_id = ? AND revoked_at IS NULL",
            (user_id,),
        )


def refresh_session(db, session_id: str) -> None:
    """Slide a live session's expiry forward to now + 7 days.

    A revoked or already-expired session is left untouched (the WHERE clause
    only matches live rows), so refresh can never resurrect a dead session.
    """
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = datetime('now', ?) "
            "WHERE session_id = ? "
            "  AND revoked_at IS NULL "
            "  AND expires_at > datetime('now')",
            (_SESSION_TTL, session_id),
        )
