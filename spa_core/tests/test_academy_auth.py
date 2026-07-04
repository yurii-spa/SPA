"""
spa_core/tests/test_academy_auth.py

Tests for the Academy auth core (spa_core/academy/auth/*).

Covers argon2id password hashing, opaque server-side sessions, invite-code
redemption, user CRUD + constant-time authentication, and the append-only
events audit helper.

stdlib + pytest only, NO network. Requires argon2-cffi installed. Every test
uses a throwaway tmp-file DB (never the repo data/ dir).
"""

from __future__ import annotations

import sqlite3

import pytest

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events, invites, passwords, sessions, users


@pytest.fixture()
def db(tmp_path):
    """A migrated AcademyDB on a tmp-file path."""
    path = tmp_path / "academy_auth_test.db"
    d = AcademyDB(db_path=str(path))
    d.run_migrations()
    return d


def _expire_session(db, raw_token):
    """Force a session's expiry into the past (test helper)."""
    session_id = sessions._hash_token(raw_token)
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = datetime('now', '-1 day') "
            "WHERE session_id = ?",
            (session_id,),
        )


# ── passwords (argon2id) ────────────────────────────────────────────────────


def test_password_hash_verify_roundtrip():
    h = passwords.hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert passwords.verify_password("correct horse battery", h) is True


def test_password_verify_wrong_password():
    h = passwords.hash_password("correct horse battery")
    assert passwords.verify_password("wrong password", h) is False


def test_password_verify_malformed_hash_is_false():
    assert passwords.verify_password("whatever", "not-a-phc-string") is False


def test_needs_rehash_fresh_hash_false():
    h = passwords.hash_password("correct horse battery")
    assert passwords.needs_rehash(h) is False


# ── sessions ────────────────────────────────────────────────────────────────


def _make_user_row(db, email="u@example.com", password="password123"):
    return users.create_user(db, email, password, is_owner=True)


def test_create_session_raw_token_differs_from_stored_id(db):
    uid = _make_user_row(db)
    raw = sessions.create_session(db, uid, ip="1.2.3.4", user_agent="pytest")
    assert isinstance(raw, str) and raw
    stored_id = sessions._hash_token(raw)
    assert stored_id != raw
    with db.connect() as conn:
        row = conn.execute(
            "SELECT session_id, user_id FROM sessions WHERE user_id = ?", (uid,)
        ).fetchone()
    assert row["session_id"] == stored_id
    assert row["user_id"] == uid


def test_get_session_returns_row_with_csrf(db):
    uid = _make_user_row(db)
    raw = sessions.create_session(db, uid)
    row = sessions.get_session(db, raw)
    assert row is not None
    assert row["user_id"] == uid
    assert row["csrf_token"]
    assert len(row["csrf_token"]) == 64  # secrets.token_hex(32)


def test_get_session_unknown_token_none(db):
    assert sessions.get_session(db, "does-not-exist") is None


def test_get_session_expired_returns_none(db):
    uid = _make_user_row(db)
    raw = sessions.create_session(db, uid)
    _expire_session(db, raw)
    assert sessions.get_session(db, raw) is None


def test_revoke_session(db):
    uid = _make_user_row(db)
    raw = sessions.create_session(db, uid)
    sessions.revoke_session(db, sessions._hash_token(raw))
    assert sessions.get_session(db, raw) is None


def test_revoke_all_sessions(db):
    uid = _make_user_row(db)
    r1 = sessions.create_session(db, uid)
    r2 = sessions.create_session(db, uid)
    sessions.revoke_all_sessions(db, uid)
    assert sessions.get_session(db, r1) is None
    assert sessions.get_session(db, r2) is None


def test_refresh_session_slides_window(db):
    uid = _make_user_row(db)
    raw = sessions.create_session(db, uid)
    sid = sessions._hash_token(raw)
    # Move expiry close to now, then refresh; still live afterwards.
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = datetime('now', '+1 minute') "
            "WHERE session_id = ?",
            (sid,),
        )
    sessions.refresh_session(db, sid)
    row = sessions.get_session(db, raw)
    assert row is not None
    # Expiry pushed out to ~7 days > 1 day from now.
    with db.connect() as conn:
        still = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ? "
            "AND expires_at > datetime('now', '+1 day')",
            (sid,),
        ).fetchone()
    assert still is not None


# ── users ───────────────────────────────────────────────────────────────────


def test_create_user_success(db):
    uid = users.create_user(db, "alice@example.com", "password123", is_owner=True)
    assert isinstance(uid, int) and uid > 0
    row = users.get_user_by_id(db, uid)
    assert row["email"] == "alice@example.com"


def test_create_user_invalid_email(db):
    with pytest.raises(ValueError):
        users.create_user(db, "not-an-email", "password123", is_owner=True)


def test_create_user_short_password(db):
    with pytest.raises(ValueError):
        users.create_user(db, "bob@example.com", "short", is_owner=True)


def test_create_user_duplicate_email_raises(db):
    users.create_user(db, "dup@example.com", "password123", is_owner=True)
    with pytest.raises((sqlite3.IntegrityError, ValueError)):
        users.create_user(db, "dup@example.com", "password456", is_owner=True)


def test_authenticate_correct_password(db):
    users.create_user(db, "carol@example.com", "password123", is_owner=True)
    row = users.authenticate(db, "carol@example.com", "password123")
    assert row is not None
    assert row["email"] == "carol@example.com"


def test_authenticate_wrong_password_none(db):
    users.create_user(db, "dave@example.com", "password123", is_owner=True)
    assert users.authenticate(db, "dave@example.com", "wrong-password") is None


def test_authenticate_unknown_email_none(db):
    # Must not raise, and must not enumerate — plain None.
    assert users.authenticate(db, "ghost@example.com", "password123") is None


def test_list_users_excludes_password_hash(db):
    users.create_user(db, "erin@example.com", "password123", is_owner=True)
    rows = users.list_users(db)
    assert rows
    assert "password_hash" not in rows[0].keys()


# ── invites ─────────────────────────────────────────────────────────────────


def test_create_and_use_invite(db):
    owner = users.create_user(db, "owner@example.com", "password123", is_owner=True)
    guest = users.create_user(db, "guest@example.com", "password123", is_owner=True)
    code = invites.create_invite(db, created_by_user_id=owner, max_uses=1)
    assert invites.use_invite(db, code, guest) is True


def test_use_invite_exhausted_second_time_false(db):
    owner = users.create_user(db, "owner2@example.com", "password123", is_owner=True)
    g1 = users.create_user(db, "g1@example.com", "password123", is_owner=True)
    g2 = users.create_user(db, "g2@example.com", "password123", is_owner=True)
    code = invites.create_invite(db, created_by_user_id=owner, max_uses=1)
    assert invites.use_invite(db, code, g1) is True
    assert invites.use_invite(db, code, g2) is False


def test_use_invite_unknown_code_false(db):
    uid = users.create_user(db, "x@example.com", "password123", is_owner=True)
    assert invites.use_invite(db, "no-such-code", uid) is False


def test_create_user_with_invite_consumes_it(db):
    owner = users.create_user(db, "owner3@example.com", "password123", is_owner=True)
    code = invites.create_invite(db, created_by_user_id=owner, max_uses=1)
    # A non-owner registers WITH the invite → invite is redeemed.
    uid = users.create_user(db, "invited@example.com", "password123", invite_code=code)
    assert isinstance(uid, int)
    inv = invites.get_invite(db, code)
    assert inv["used_count"] == 1
    assert str(uid) in inv["used_by"]
    # The 1-use invite is now exhausted — a second registration fails atomically.
    with pytest.raises(ValueError):
        users.create_user(db, "toolate@example.com", "password123", invite_code=code)
    assert users.get_user_by_email(db, "toolate@example.com") is None


def test_create_user_invalid_invite_creates_no_user(db):
    with pytest.raises(ValueError):
        users.create_user(db, "nope@example.com", "password123", invite_code="bogus")
    assert users.get_user_by_email(db, "nope@example.com") is None


# ── events ──────────────────────────────────────────────────────────────────


def test_log_event_is_persisted(db):
    uid = users.create_user(db, "log@example.com", "password123", is_owner=True)
    events.log_event(db, "admin_view", user_id=uid, payload={"k": "v"}, ip="9.9.9.9")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT action, user_id, payload_json, ip FROM events "
            "WHERE action = 'admin_view'"
        ).fetchone()
    assert row is not None
    assert row["user_id"] == uid
    assert row["ip"] == "9.9.9.9"
    assert "\"k\":\"v\"" in row["payload_json"]
