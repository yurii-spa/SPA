"""
spa_core/academy/auth/users.py

User CRUD + authentication for the Academy.

Security properties:
  - Passwords are hashed with argon2id (spa_core.academy.auth.passwords).
  - authenticate() runs in constant time w.r.t. account existence: when the
    email is unknown it still performs a verify against a dummy hash, so an
    attacker cannot distinguish "no such user" from "wrong password" by timing.
  - Successful logins transparently re-hash the password if the stored hash was
    produced with weaker/older parameters (needs_rehash).
  - Registration with an invite code is atomic: the user row and the invite
    counter bump commit together, or neither does — a failed redemption leaves
    no orphan user, and a failed insert never burns an invite.

LLM FORBIDDEN in this module (auth/security-adjacent).
Academy stage 2.
"""

from __future__ import annotations

import re
import sqlite3
from typing import List, Optional

from spa_core.academy.auth import events, passwords

# Email validation: pragmatic, not RFC-5322-complete. Rejects whitespace and
# requires a single @ with a dotted domain. Length capped at 254 (SMTP limit).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_EMAIL_LEN = 254
_MIN_PASSWORD_LEN = 10

# Columns returned to callers (never the password_hash).
_PUBLIC_COLS = "id, email, invite_code_used, is_owner, created_at"

# Cached dummy argon2 hash used to keep authenticate() constant-time when an
# email is unknown. Built lazily on first miss.
_DUMMY_HASH: Optional[str] = None


def _dummy_hash() -> str:
    """Return a cached argon2 hash of a throwaway value (for timing parity)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = passwords.hash_password("x" * _MIN_PASSWORD_LEN)
    return _DUMMY_HASH


def _validate_email(email: str) -> str:
    if not email or len(email) > _MAX_EMAIL_LEN or not _EMAIL_RE.match(email):
        raise ValueError("invalid email")
    return email


def _validate_password(password: str) -> None:
    if not password or len(password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LEN} characters")


def create_user(
    db,
    email: str,
    password: str,
    invite_code: Optional[str] = None,
    is_owner: bool = False,
) -> int:
    """Create a user and return its new id.

    Args:
        email: Validated (regex + max 254 chars).
        password: Validated (>= 10 chars), hashed with argon2id.
        invite_code: If given, redeemed atomically with the insert; a failed
            redemption raises ValueError("invalid invite") and creates no user.
            Ignored requirement-wise when is_owner=True (owners self-register).
        is_owner: Owner accounts do not require an invite.

    Raises:
        ValueError: On invalid email/password, or an invalid/exhausted invite.
        sqlite3.IntegrityError: On a duplicate email.
    """
    _validate_email(email)
    _validate_password(password)
    pw_hash = passwords.hash_password(password)

    with db.connect() as conn:
        # Insert with a NULL invite reference first: the users.invite_code_used
        # FK would reject a bogus code outright (IntegrityError), but we want a
        # clean ValueError. We set the reference only after a successful redeem.
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, invite_code_used, is_owner) "
            "VALUES (?, ?, NULL, ?)",
            (email, pw_hash, 1 if is_owner else 0),
        )
        user_id = cur.lastrowid

        if invite_code:
            # Atomic redemption in the SAME transaction as the insert — mirrors
            # invites.use_invite, but sharing this connection so a bad invite
            # rolls back the user too (context manager rolls back on raise).
            redeemed = conn.execute(
                "UPDATE invite_codes "
                "SET used_count = used_count + 1, "
                "    used_by = json_insert(used_by, '$[#]', ?), "
                "    used_at = datetime('now') "
                "WHERE code = ? AND used_count < max_uses",
                (user_id, invite_code),
            )
            if redeemed.rowcount != 1:
                raise ValueError("invalid invite")
            conn.execute(
                "UPDATE users SET invite_code_used = ? WHERE id = ?",
                (invite_code, user_id),
            )

    events.log_event(db, "register", user_id=user_id)
    return user_id


def get_user_by_email(db, email: str) -> Optional[sqlite3.Row]:
    """Return the full user Row (incl. password_hash) for *email*, or None.

    Includes password_hash because authenticate() relies on it; callers that
    surface user data to the outside should use list_users() instead.
    """
    if not email:
        return None
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()


def get_user_by_id(db, user_id: int) -> Optional[sqlite3.Row]:
    """Return the full user Row (incl. password_hash) for *user_id*, or None."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def authenticate(db, email: str, password: str) -> Optional[sqlite3.Row]:
    """Return the user Row on a correct password, else None (constant time).

    An unknown email still triggers a verify against a dummy hash so the code
    path — and therefore the timing — is indistinguishable from a wrong
    password on a real account. Never raises on a missing user.
    """
    row = get_user_by_email(db, email) if email else None
    if row is None:
        # Burn equivalent time; result is discarded.
        passwords.verify_password(password or "", _dummy_hash())
        events.log_event(db, "login_failed", payload={"email": email})
        return None

    stored = row["password_hash"]
    if not passwords.verify_password(password or "", stored):
        events.log_event(db, "login_failed", user_id=row["id"])
        return None

    # Correct password — transparently upgrade the hash if parameters moved on.
    if passwords.needs_rehash(stored):
        update_password(db, row["id"], password)

    events.log_event(db, "login", user_id=row["id"])
    return row


def update_password(db, user_id: int, new_password: str) -> None:
    """Re-hash and store a new password for *user_id*, writing an audit event."""
    _validate_password(new_password)
    pw_hash = passwords.hash_password(new_password)
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pw_hash, user_id),
        )
    events.log_event(db, "password_change", user_id=user_id)


def list_users(db) -> List[sqlite3.Row]:
    """Return every user as a Row WITHOUT the password_hash column."""
    with db.connect() as conn:
        return conn.execute(
            f"SELECT {_PUBLIC_COLS} FROM users ORDER BY id"
        ).fetchall()
