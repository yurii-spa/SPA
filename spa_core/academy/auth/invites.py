"""
spa_core/academy/auth/invites.py

Invite-code management for the Academy (closed-registration onboarding).

An invite code is a random secrets.token_urlsafe(12) string with a max-uses
counter. Redemption is atomic: use_invite performs a single UPDATE guarded by
`used_count < max_uses`, so two concurrent redemptions of a 1-use code can never
both succeed — SQLite serialises the writes and exactly one sees rowcount == 1.

The redeeming user's id is appended to a JSON `used_by` array via
json_insert(used_by, '$[#]', user_id) in the same statement, keeping the audit
of who consumed the code atomic with the counter bump.

LLM FORBIDDEN in this module (auth/security-adjacent).
Academy stage 2.
"""

from __future__ import annotations

import secrets
import sqlite3
from typing import List, Optional


def create_invite(db, created_by_user_id: Optional[int] = None, max_uses: int = 1) -> str:
    """Create an invite code and return it.

    Args:
        created_by_user_id: The owner/admin user id that minted the code
            (may be None for a bootstrap code).
        max_uses: How many times the code may be redeemed (>= 1).
    """
    if max_uses < 1:
        raise ValueError("max_uses must be >= 1")
    code = secrets.token_urlsafe(12)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO invite_codes(code, created_by, max_uses) VALUES (?, ?, ?)",
            (code, created_by_user_id, max_uses),
        )
    return code


def use_invite(db, code: str, user_id: int) -> bool:
    """Atomically redeem *code* for *user_id*.

    Returns True iff the code existed and had remaining uses (rowcount == 1).
    Returns False if the code is unknown or already exhausted.
    """
    if not code:
        return False
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE invite_codes "
            "SET used_count = used_count + 1, "
            "    used_by = json_insert(used_by, '$[#]', ?), "
            "    used_at = datetime('now') "
            "WHERE code = ? AND used_count < max_uses",
            (user_id, code),
        )
        return cur.rowcount == 1


def get_invite(db, code: str) -> Optional[sqlite3.Row]:
    """Return the invite_codes Row for *code*, or None."""
    if not code:
        return None
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM invite_codes WHERE code = ?", (code,)
        ).fetchone()


def list_invites(db) -> List[sqlite3.Row]:
    """Return all invite codes, newest first."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM invite_codes ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
