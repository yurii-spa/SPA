"""
spa_core/academy/auth/events.py

Thin append-only audit-log helper for the Academy `events` table.

The events table is enforced append-only at the DB layer (BEFORE UPDATE/DELETE
triggers RAISE(ABORT)), so this helper only ever INSERTs. The payload is stored
as a JSON string in payload_json.

Canonical action strings (keep this list authoritative — callers should use one
of these rather than inventing ad-hoc verbs):
    register, login, login_failed, logout, logout_everywhere,
    siwe_nonce, siwe_verify, wallet_bind,
    verify_submit, verify_pass, verify_fail,
    quiz_submit, note_save, export, admin_view, lockout

LLM FORBIDDEN in this module (audit/security-adjacent).
Academy stage 2.
"""

from __future__ import annotations

import json
from typing import Optional


# Canonical, documented action verbs (advisory allow-list).
KNOWN_ACTIONS = frozenset(
    {
        "register",
        "login",
        "login_failed",
        "logout",
        "logout_everywhere",
        "siwe_nonce",
        "siwe_verify",
        "wallet_bind",
        "verify_submit",
        "verify_pass",
        "verify_fail",
        "quiz_submit",
        "note_save",
        "export",
        "admin_view",
        "lockout",
    }
)


def log_event(
    db,
    action: str,
    user_id: Optional[int] = None,
    payload: Optional[dict] = None,
    ip: Optional[str] = None,
) -> None:
    """Append one row to the events audit log.

    Args:
        action: One of KNOWN_ACTIONS (not enforced — the DB accepts any string,
            but callers should stick to the canonical verbs).
        user_id: The acting user, or None for pre-auth / anonymous events.
        payload: Optional structured context, JSON-serialised into payload_json.
        ip: Optional source IP string.
    """
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True) if payload is not None else None
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO events(user_id, action, payload_json, ip) VALUES (?, ?, ?, ?)",
            (user_id, action, payload_json, ip),
        )
